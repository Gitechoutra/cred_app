import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Sheet, Skeleton, Tabs, cx } from '../ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime } from '../../utils/format';

/** Ticket status, as every staff screen shows it. */
export const TICKET_TONES = {
  Open: 'warn',
  'In progress': 'neutral',
  Resolved: 'good',
  Closed: 'neutral',
};

export function TicketStatusBadge({ ticket }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={TICKET_TONES[ticket.status_label] || 'neutral'} dot>
        {ticket.status_label}
      </Badge>
      {ticket.waiting_on && (
        <span className="text-2xs text-slate">waiting on {ticket.waiting_on}</span>
      )}
      {ticket.escalated && <Badge tone="alert">Escalated</Badge>}
    </span>
  );
}

const AUDIT_LABELS = {
  SUPPORT_TICKET_CREATED: 'Ticket raised',
  SUPPORT_ASSIGNED: 'Assigned',
  SUPPORT_UNASSIGNED: 'Released',
  SUPPORT_REPLY_SENT: 'Replied to customer',
  SUPPORT_NOTE_ADDED: 'Internal note added',
  SUPPORT_STATUS_CHANGED: 'Status changed',
  SUPPORT_ESCALATED: 'Escalated to admins',
};

/**
 * One ticket, worked from start to finish: the conversation with internal
 * notes kept visibly apart, a composer for replies or notes, status,
 * assignment, escalation, the customer, and the audit trail.
 *
 * `customerPath` links to the customer profile; null where the viewer has no
 * customer screen. `canEscalate` is false for admins - they are who an
 * escalation goes to.
 */
export default function TicketWorkspace({ ticketId, backTo, customerPath, canEscalate = true }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { data: ticket, loading, error, refetch } = useFetch(
    () => endpoints.desk.ticket(ticketId), [ticketId],
  );
  const [mode, setMode] = useState('reply');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [sheetText, setSheetText] = useState('');

  if (loading && !ticket) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-72 w-full rounded-2xl" />
      </div>
    );
  }
  if (error || !ticket) {
    return (
      <Card className="text-center">
        <p className="font-semibold text-ink">Could not load this ticket</p>
        <p className="mt-1 text-sm text-slate">{error?.message}</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={refetch}>Try again</Button>
      </Card>
    );
  }

  async function act(fn, success) {
    setBusy(true);
    try {
      const response = await fn();
      toast.success(success || response.message);
      await refetch();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function send(event) {
    event.preventDefault();
    if (!text.trim()) return;
    const ok = await act(() => (mode === 'reply'
      ? endpoints.desk.reply(ticket.ticket_id, text.trim())
      : endpoints.desk.note(ticket.ticket_id, text.trim())));
    if (ok) setText('');
  }

  const closed = ticket.status === 'CLOSED';

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-start gap-3">
          {backTo && (
            <button
              type="button"
              onClick={() => navigate(backTo)}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-line text-slate transition hover:bg-mist hover:text-ink"
              aria-label="Back"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
                <path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          <div className="min-w-0 flex-1">
            <p className="money text-2xs font-semibold uppercase tracking-wider text-slate">
              {ticket.ticket_number} · {ticket.category?.replace(/_/g, ' ').toLowerCase()} · {ticket.priority?.toLowerCase()} priority
            </p>
            <h1 className="mt-1 text-xl font-bold text-ink">{ticket.subject}</h1>
            <div className="mt-2"><TicketStatusBadge ticket={ticket} /></div>
          </div>
        </div>

        {ticket.escalated && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3.5 text-sm text-red-900">
            <span className="font-semibold">Escalated {dateTime(ticket.escalated_at)}.</span>{' '}
            {ticket.escalation_reason}
          </div>
        )}
        {ticket.resolution_notes && (
          <div className="rounded-xl border border-mint-200 bg-mint-50 p-3.5 text-sm text-mint-900">
            <span className="font-semibold">Resolution:</span> {ticket.resolution_notes}
          </div>
        )}

        <Card className="space-y-3">
          {ticket.messages.map((message) => (
            <Message key={message.message_id} message={message} />
          ))}
        </Card>

        <Card>
          <form onSubmit={send} className="space-y-3">
            <Tabs
              tabs={[{ value: 'reply', label: 'Reply to customer' }, { value: 'note', label: 'Internal note' }]}
              active={mode}
              onChange={setMode}
            />
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              maxLength={4000}
              disabled={closed && mode === 'reply'}
              placeholder={mode === 'reply'
                ? (closed ? 'This ticket is closed. Reopen it to reply.' : 'Write to the customer…')
                : 'Visible to staff only. The customer never sees notes.'}
              className={cx(
                'w-full resize-y rounded-xl border px-3.5 py-3 text-[15px] text-ink outline-none transition',
                'placeholder:text-slate-light focus:ring-2 focus:ring-mint/20',
                mode === 'note' ? 'border-amber-200 bg-amber-50/60' : 'border-line bg-canvas',
              )}
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-2xs text-slate">
                {mode === 'reply' ? 'The customer is notified in the app.' : 'Staff-only. Recorded in the audit trail.'}
              </p>
              <Button type="submit" variant={mode === 'reply' ? 'mint' : 'outline'} loading={busy}
                disabled={!text.trim() || (closed && mode === 'reply')}
              >
                {mode === 'reply' ? 'Send reply' : 'Add note'}
              </Button>
            </div>
          </form>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card className="space-y-3">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Status</p>
          <div className="grid grid-cols-2 gap-2">
            {[
              ['OPEN', 'Open'], ['IN_PROGRESS', 'In progress'],
              ['RESOLVED', 'Resolved'], ['CLOSED', 'Closed'],
            ].map(([value, label]) => {
              const current = ticket.status_label === label;
              return (
                <button
                  key={value}
                  type="button"
                  disabled={busy || current}
                  onClick={() => (value === 'RESOLVED'
                    ? (setSheetText(ticket.resolution_notes || ''), setResolveOpen(true))
                    : act(() => endpoints.desk.setStatus(ticket.ticket_id, value)))}
                  className={cx(
                    'rounded-xl border px-3 py-2 text-sm font-medium transition',
                    current ? 'border-ink bg-ink text-white' : 'border-line text-ink hover:bg-mist',
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div className="border-t border-line pt-3">
            <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Assigned to</p>
            <p className="mt-1 text-sm text-ink">{ticket.assigned_agent_name || 'Nobody yet'}</p>
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="outline" disabled={busy}
                onClick={() => act(() => endpoints.desk.assign(ticket.ticket_id, true))}
              >
                Assign to me
              </Button>
              {ticket.assigned_agent_id && (
                <Button size="sm" variant="ghost" disabled={busy}
                  onClick={() => act(() => endpoints.desk.assign(ticket.ticket_id, false))}
                >
                  Release
                </Button>
              )}
            </div>
          </div>

          {canEscalate && !ticket.escalated && (
            <div className="border-t border-line pt-3">
              <Button size="sm" variant="outline" full disabled={busy}
                onClick={() => { setSheetText(''); setEscalateOpen(true); }}
              >
                Escalate to admin
              </Button>
              <p className="mt-1.5 text-2xs leading-relaxed text-slate">
                For refunds, limits, KYC, payment disputes or account status -
                decisions an agent cannot make.
              </p>
            </div>
          )}
        </Card>

        <Card className="space-y-2">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Customer</p>
          <p className="text-sm font-semibold text-ink">{ticket.customer?.full_name || '—'}</p>
          <p className="money text-xs text-slate">+91 {ticket.customer?.phone_masked}</p>
          {customerPath && ticket.customer?.user_id && (
            <Button size="sm" variant="outline" onClick={() => navigate(customerPath(ticket.customer.user_id))}>
              Open customer profile
            </Button>
          )}
        </Card>

        <Card>
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Audit trail</p>
          <ol className="mt-2 space-y-2.5">
            {ticket.audit_trail.length === 0 && (
              <li className="text-sm text-slate">No staff actions yet.</li>
            )}
            {ticket.audit_trail.map((row, index) => (
              <li key={index} className="border-l-2 border-line pl-3">
                <p className="text-sm font-medium text-ink">{AUDIT_LABELS[row.action] || row.action}</p>
                <p className="text-2xs text-slate">
                  {row.actor_name || 'Customer'} · {dateTime(row.at)}
                </p>
                {row.notes && <p className="mt-0.5 text-xs text-slate">{row.notes}</p>}
              </li>
            ))}
          </ol>
        </Card>
      </aside>

      <Sheet
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        title="Resolve ticket"
        footer={(
          <Button variant="mint" size="lg" full loading={busy} disabled={!sheetText.trim()}
            onClick={async () => {
              const ok = await act(() => endpoints.desk.setStatus(ticket.ticket_id, 'RESOLVED', sheetText.trim()));
              if (ok) setResolveOpen(false);
            }}
          >
            Mark resolved
          </Button>
        )}
      >
        <p className="mb-2 text-sm text-slate">How was it resolved? The customer sees this.</p>
        <textarea
          rows={4}
          maxLength={1000}
          value={sheetText}
          onChange={(e) => setSheetText(e.target.value)}
          className="w-full rounded-xl border border-line px-3.5 py-3 text-[15px] outline-none focus:ring-2 focus:ring-mint/20"
        />
      </Sheet>

      <Sheet
        open={escalateOpen}
        onClose={() => setEscalateOpen(false)}
        title="Escalate to admin"
        footer={(
          <Button variant="mint" size="lg" full loading={busy} disabled={sheetText.trim().length < 10}
            onClick={async () => {
              const ok = await act(() => endpoints.desk.escalate(ticket.ticket_id, sheetText.trim()));
              if (ok) setEscalateOpen(false);
            }}
          >
            Escalate
          </Button>
        )}
      >
        <p className="mb-2 text-sm text-slate">
          What does the administrator need to decide? At least 10 characters.
        </p>
        <textarea
          rows={4}
          maxLength={500}
          value={sheetText}
          onChange={(e) => setSheetText(e.target.value)}
          className="w-full rounded-xl border border-line px-3.5 py-3 text-[15px] outline-none focus:ring-2 focus:ring-mint/20"
        />
      </Sheet>
    </div>
  );
}

function Message({ message }) {
  const internal = message.is_internal;
  const fromCustomer = message.sender_role === 'USER';
  const system = message.sender_role === 'SYSTEM';
  return (
    <div className={cx('flex', fromCustomer ? 'justify-start' : 'justify-end')}>
      <div
        className={cx(
          'max-w-[85%] rounded-2xl px-3.5 py-2.5',
          internal && 'border border-amber-200 bg-amber-50',
          !internal && fromCustomer && 'bg-mist',
          !internal && !fromCustomer && !system && 'bg-ink text-white',
          !internal && system && 'border border-line bg-canvas',
        )}
      >
        <p className={cx('text-2xs font-semibold',
          internal ? 'text-amber-800' : (!fromCustomer && !system ? 'text-white/70' : 'text-slate'))}
        >
          {internal ? `Internal note · ${message.sender_name}` : message.sender_name || message.sender_role}
          {' · '}{dateTime(message.created_on)}
        </p>
        <p className="mt-1 whitespace-pre-wrap text-sm">{message.body}</p>
      </div>
    </div>
  );
}
