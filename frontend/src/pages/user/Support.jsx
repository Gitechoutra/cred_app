import { useState } from 'react';

import { endpoints } from '../../api/client';
import { PageHeader, IconReceipt } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Input, Sheet, Skeleton, cx,
} from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime, statusLabel, statusTone, titleCase } from '../../utils/format';

const CATEGORIES = [
  { value: 'PAYMENT_ISSUE', label: 'Payment issue' },
  { value: 'EMI_ISSUE', label: 'EMI issue' },
  { value: 'CARD_ISSUE', label: 'Card issue' },
  { value: 'KYC_ISSUE', label: 'KYC issue' },
  { value: 'REFUND_STATUS', label: 'Refund status' },
  { value: 'OTHER', label: 'Something else' },
];

export default function Support() {
  const toast = useToast();

  const { data: tickets, loading, refetch } = useFetch(() => endpoints.support.tickets(), []);

  const [composing, setComposing] = useState(false);
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({ subject: '', message: '', category: 'OTHER' });
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!form.subject.trim() || !form.message.trim() || busy) return;
    setBusy(true);

    try {
      const response = await endpoints.support.create(form);
      toast.success(response.message);
      setComposing(false);
      setForm({ subject: '', message: '', category: 'OTHER' });
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function openTicket(ticket) {
    try {
      const response = await endpoints.support.get(ticket.ticket_id);
      setOpen(response.data);
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function sendReply() {
    if (!reply.trim() || busy) return;
    setBusy(true);

    try {
      const response = await endpoints.support.reply(open.ticket_id, reply.trim());
      setOpen(response.data);
      setReply('');
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Help and support"
          back="/profile"
          action={
            <button
              type="button"
              onClick={() => setComposing(true)}
              className="text-xs font-semibold text-mint-700"
            >
              New ticket
            </button>
          }
        />

        <div className="px-4 pt-4">
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }, (_, i) => (
                <Skeleton key={i} className="h-20 w-full rounded-2xl" />
              ))}
            </div>
          ) : !tickets?.length ? (
            <div className="pt-8">
              <EmptyState
                icon={<IconReceipt className="h-6 w-6" />}
                title="No tickets yet"
                description="Raise a ticket and our team will respond within 24 hours."
                action={
                  <Button variant="mint" onClick={() => setComposing(true)}>
                    Raise a ticket
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="space-y-2">
              {tickets.map((ticket) => (
                <button
                  key={ticket.ticket_id}
                  type="button"
                  onClick={() => openTicket(ticket)}
                  className="w-full rounded-2xl border border-line bg-canvas p-3.5 text-left transition hover:shadow-card"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
                      {ticket.subject}
                    </p>
                    <Badge tone={statusTone(ticket.status)} className="shrink-0">
                      {statusLabel(ticket.status)}
                    </Badge>
                  </div>

                  <p className="money mt-1 text-2xs text-slate">
                    {ticket.ticket_number} · {titleCase(ticket.category)} ·{' '}
                    {dateTime(ticket.created_on)}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── New ticket ──────────────────────────────────────────────── */}
      <Sheet
        open={composing}
        onClose={() => setComposing(false)}
        title="Raise a ticket"
        footer={
          <Button
            variant="mint"
            size="lg"
            full
            loading={busy}
            disabled={!form.subject.trim() || !form.message.trim()}
            onClick={create}
          >
            Submit
          </Button>
        }
      >
        <div className="space-y-4 pb-2">
          <div>
            <span className="mb-2 block text-sm font-medium text-ink">What is this about?</span>
            <div className="grid grid-cols-2 gap-2">
              {CATEGORIES.map((category) => (
                <button
                  key={category.value}
                  type="button"
                  onClick={() => setForm({ ...form, category: category.value })}
                  className={cx(
                    'rounded-xl border px-3 py-2.5 text-xs font-medium transition',
                    form.category === category.value
                      ? 'border-mint bg-mint-50 text-ink'
                      : 'border-line text-slate hover:border-ink/20',
                  )}
                >
                  {category.label}
                </button>
              ))}
            </div>
          </div>

          <Input
            label="Subject"
            placeholder="Payment stuck since yesterday"
            value={form.subject}
            onChange={(event) => setForm({ ...form, subject: event.target.value })}
          />

          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink">Describe the issue</span>
            <textarea
              rows={5}
              placeholder="Tell us what happened, and include the UTR if you have one."
              value={form.message}
              onChange={(event) => setForm({ ...form, message: event.target.value })}
              className="w-full rounded-xl border border-line bg-canvas p-3.5 text-[15px] text-ink outline-none transition focus:border-ink/40 placeholder:text-slate-light"
            />
          </div>
        </div>
      </Sheet>

      {/* ── Thread ──────────────────────────────────────────────────── */}
      <Sheet
        open={Boolean(open)}
        onClose={() => setOpen(null)}
        title={open?.subject}
        footer={
          open && open.status !== 'CLOSED' ? (
            <div className="flex gap-2">
              <input
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder="Write a reply…"
                className="h-12 flex-1 rounded-xl border border-line bg-canvas px-3.5 text-[15px] outline-none focus:border-ink/40"
              />
              <Button variant="mint" size="lg" loading={busy} onClick={sendReply}>
                Send
              </Button>
            </div>
          ) : null
        }
      >
        {open && (
          <div className="space-y-3 pb-2">
            <p className="money text-2xs text-slate">
              {open.ticket_number} · {statusLabel(open.status)}
            </p>

            {open.messages?.map((message) => (
              <div
                key={message.message_id}
                className={cx(
                  'max-w-[85%] rounded-2xl px-3.5 py-2.5',
                  message.sender_role === 'USER'
                    ? 'ml-auto bg-ink text-white'
                    : 'bg-mist text-ink',
                )}
              >
                <p className="text-sm leading-relaxed">{message.body}</p>
                <p
                  className={cx(
                    'mt-1 text-2xs',
                    message.sender_role === 'USER' ? 'text-white/50' : 'text-slate',
                  )}
                >
                  {message.sender_role === 'USER' ? 'You' : message.sender_name || 'CashU'} ·{' '}
                  {dateTime(message.created_on)}
                </p>
              </div>
            ))}
          </div>
        )}
      </Sheet>
    </div>
  );
}
