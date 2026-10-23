import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import TicketWorkspace, { TicketStatusBadge } from '../../components/support/TicketWorkspace';
import { Badge, Button, Card, Input, Sheet, Skeleton, Tabs } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime, money } from '../../utils/format';
import { AdminHeader, DataTable, StatCard } from './AdminLayout';

function Failed({ error, onRetry }) {
  return (
    <Card className="text-center">
      <p className="font-semibold text-ink">Could not load this page</p>
      <p className="mt-1 text-sm text-slate">{error?.message}</p>
      {onRetry && <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>Try again</Button>}
    </Card>
  );
}

const OUTCOME_TONE = { SUCCESS: 'good', FAILED: 'alert', PENDING: 'warn', OTHER: 'neutral' };

/* ── Staff (L3) ───────────────────────────────────────────────────────── */

/**
 * Who works on the consoles. A staff account is a registered CashU account
 * given a role - the same OTP + MPIN sign-in, through its own portal. Changing
 * a role signs the account out everywhere.
 */
export function AdminStaff() {
  const toast = useToast();
  const { data, loading, error, refetch } = useFetch(() => endpoints.admin.staff(), []);
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState('L1_SUPPORT');
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState('');

  async function add() {
    setBusy(true);
    setFieldError('');
    try {
      const response = await endpoints.admin.addStaff(phone, role);
      toast.success(response.message);
      setOpen(false);
      setPhone('');
      refetch();
    } catch (err) {
      setFieldError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function change(member, nextRole) {
    const removing = nextRole === 'NORMAL_USER';
    if (removing && !window.confirm(`Remove staff access for ${member.full_name}? They will be signed out.`)) return;
    try {
      const response = await endpoints.admin.setStaffRole(member.user_id, nextRole);
      toast.success(response.message);
      refetch();
    } catch (err) {
      toast.error(err.message);
    }
  }

  if (error) return <Failed error={error} onRetry={refetch} />;
  if (loading && !data) return <Skeleton className="h-64 w-full rounded-2xl" />;

  const grantable = data.grantable_roles;
  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader
        title="Staff"
        subtitle="Support agents and admins. Changing a role signs that account out everywhere."
        action={<Button variant="mint" size="sm" onClick={() => setOpen(true)}>Add staff</Button>}
      />
      <DataTable
        empty="No staff accounts."
        rows={data.staff.map((s) => ({ ...s, id: s.user_id }))}
        columns={[
          { key: 'full_name', label: 'Name', render: (r) => <span className="font-semibold">{r.full_name}</span> },
          { key: 'phone', label: 'Mobile', render: (r) => <span className="money">+91 {r.phone_masked}</span> },
          { key: 'role', label: 'Role', render: (r) => <Badge tone={r.role === 'L1_SUPPORT' ? 'neutral' : 'good'}>{r.role_label}</Badge> },
          { key: 'last', label: 'Last sign-in', render: (r) => (r.last_login ? dateTime(r.last_login) : '—') },
          { key: 'actions', label: '', render: (r) => (r.role === 'L3_SUPER_ADMIN' ? (
            <span className="text-2xs text-slate">Managed in server config</span>
          ) : (
            <div className="flex gap-2">
              {grantable.filter((g) => g.role !== r.role).map((g) => (
                <Button key={g.role} size="sm" variant="outline" onClick={() => change(r, g.role)}>
                  Make {g.role === 'L1_SUPPORT' ? 'support' : 'L2 admin'}
                </Button>
              ))}
              <Button size="sm" variant="ghost" onClick={() => change(r, 'NORMAL_USER')}>Remove</Button>
            </div>
          )) },
        ]}
      />

      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="Add staff"
        footer={(
          <Button variant="mint" size="lg" full loading={busy} disabled={!/^[6-9]\d{9}$/.test(phone)} onClick={add}>
            Grant access
          </Button>
        )}
      >
        <div className="space-y-4">
          <p className="text-sm text-slate">
            The person must already have a CashU account with an MPIN. They will
            sign in through the {role === 'L1_SUPPORT' ? 'support' : 'admin'} portal.
          </p>
          <Input
            label="Their registered mobile number"
            prefix="+91"
            inputMode="numeric"
            maxLength={10}
            value={phone}
            error={fieldError}
            onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
          />
          <Tabs
            tabs={grantable.map((g) => ({ value: g.role, label: g.role === 'L1_SUPPORT' ? 'Customer support' : 'Risk admin (L2)' }))}
            active={role}
            onChange={setRole}
          />
        </div>
      </Sheet>
    </div>
  );
}

/* ── Escalations ───────────────────────────────────────────────────────── */

export function AdminEscalations() {
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useFetch(() => endpoints.admin.escalations(), []);
  if (error) return <Failed error={error} onRetry={refetch} />;
  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader title="Escalations" subtitle="Tickets support has passed to admins. Unresolved first." />
      {loading && !data ? <Skeleton className="h-64 w-full rounded-2xl" /> : (
        <DataTable
          empty="Nothing has been escalated."
          rows={(data || []).map((t) => ({ ...t, id: t.ticket_id }))}
          onRowClick={(row) => navigate(`/admin/escalations/${row.ticket_id}`)}
          columns={[
            { key: 'ticket_number', label: 'Ticket', render: (r) => <span className="money font-semibold">{r.ticket_number}</span> },
            { key: 'subject', label: 'Subject', render: (r) => <span className="block max-w-[240px] truncate">{r.subject}</span> },
            { key: 'reason', label: 'Why', render: (r) => <span className="block max-w-[280px] truncate text-slate">{r.escalation_reason}</span> },
            { key: 'customer', label: 'Customer', render: (r) => r.customer?.full_name || '—' },
            { key: 'status', label: 'Status', render: (r) => <TicketStatusBadge ticket={r} /> },
            { key: 'when', label: 'Escalated', render: (r) => dateTime(r.escalated_at) },
          ]}
        />
      )}
    </div>
  );
}

export function AdminEscalation() {
  const { ticketId } = useParams();
  return (
    <TicketWorkspace
      ticketId={ticketId}
      backTo="/admin/escalations"
      customerPath={(id) => `/admin/users?highlight=${id}`}
      canEscalate={false}
    />
  );
}

/* ── Payments ──────────────────────────────────────────────────────────── */

export function AdminPayments() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') || '';
  const kind = params.get('kind') || '';
  const qs = `?per_page=50${status ? `&status=${status}` : ''}${kind ? `&kind=${kind}` : ''}`;
  const { data, loading, error, refetch } = useFetch(() => endpoints.admin.payments(qs), [qs]);

  const set = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };

  if (error) return <Failed error={error} onRetry={refetch} />;
  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader
        title="Payments"
        subtitle="Credit line, EMI and Pay Bills payments. Statuses come from gateway verification and webhooks, never from the app."
      />
      <div className="flex flex-wrap gap-3">
        <Tabs
          className="max-w-md"
          tabs={[{ value: '', label: 'All' }, { value: 'FAILED', label: 'Failed' }, { value: 'PENDING', label: 'Pending' }, { value: 'SUCCESS', label: 'Successful' }]}
          active={status}
          onChange={(v) => set('status', v)}
        />
        <Tabs
          className="max-w-md"
          tabs={[{ value: '', label: 'Every kind' }, { value: 'CREDIT', label: 'Credit line' }, { value: 'EMI', label: 'EMI' }, { value: 'BILL', label: 'Pay Bills' }]}
          active={kind}
          onChange={(v) => set('kind', v)}
        />
      </div>
      {loading && !data ? <Skeleton className="h-64 w-full rounded-2xl" /> : (
        <DataTable
          empty="No payments match."
          rows={(data || []).map((p, i) => ({ ...p, id: `${p.kind}-${p.id || i}` }))}
          columns={[
            { key: 'kind', label: 'Kind', render: (r) => ({ CREDIT: 'Credit line', EMI: 'EMI', BILL: 'Pay Bills' }[r.kind]) },
            { key: 'type', label: 'Type', render: (r) => (r.type || '').replace(/_/g, ' ').toLowerCase() },
            { key: 'customer', label: 'Customer', render: (r) => <span>{r.customer}<span className="money ml-1.5 text-2xs text-slate">{r.customer_phone}</span></span> },
            { key: 'amount', label: 'Amount', render: (r) => <span className="money">{money(r.amount)}</span> },
            { key: 'status', label: 'Status', render: (r) => <Badge tone={OUTCOME_TONE[r.outcome]}>{r.status}</Badge> },
            { key: 'reason', label: 'Failure reason', render: (r) => <span className="block max-w-[220px] truncate text-slate">{r.failure_reason || '—'}</span> },
            { key: 'reference', label: 'Reference', render: (r) => <span className="money text-xs">{r.reference}</span> },
            { key: 'at', label: 'When', render: (r) => dateTime(r.at) },
          ]}
        />
      )}
    </div>
  );
}

/* ── Error log ────────────────────────────────────────────────────────── */

export function AdminErrors() {
  const toast = useToast();
  const [resolved, setResolved] = useState('false');
  const qs = `?per_page=50${resolved ? `&resolved=${resolved}` : ''}`;
  const { data, loading, error, refetch } = useFetch(() => endpoints.admin.transactionErrors(qs), [qs]);

  async function resolve(row) {
    const note = window.prompt('How was this handled? (kept with the error)');
    if (!note) return;
    try {
      await endpoints.admin.resolveTransactionError(row.error_id, note);
      toast.success('Marked as resolved.');
      refetch();
    } catch (err) {
      toast.error(err.message);
    }
  }

  if (error) return <Failed error={error} onRetry={refetch} />;
  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader title="Error log" subtitle="Payment failures recorded by the server, with the gateway's reason." />
      <Tabs
        className="max-w-sm"
        tabs={[{ value: 'false', label: 'Unresolved' }, { value: 'true', label: 'Resolved' }, { value: '', label: 'All' }]}
        active={resolved}
        onChange={setResolved}
      />
      {loading && !data ? <Skeleton className="h-64 w-full rounded-2xl" /> : (
        <DataTable
          empty="No errors here."
          rows={(data || []).map((e) => ({ ...e, id: e.error_id }))}
          columns={[
            { key: 'code', label: 'Code', render: (r) => <span className="money text-xs font-semibold">{r.error_code}</span> },
            { key: 'type', label: 'Type', render: (r) => <Badge tone="alert">{r.error_type}</Badge> },
            { key: 'message', label: 'Message', render: (r) => <span className="block max-w-[320px] truncate">{r.error_message}</span> },
            { key: 'amount', label: 'Amount', render: (r) => <span className="money">{money(r.amount)}</span> },
            { key: 'method', label: 'Method', render: (r) => r.payment_method || '—' },
            { key: 'at', label: 'When', render: (r) => dateTime(r.created_at) },
            { key: 'action', label: '', render: (r) => (r.is_resolved
              ? <Badge tone="good">Resolved</Badge>
              : <Button size="sm" variant="outline" onClick={() => resolve(r)}>Resolve</Button>) },
          ]}
        />
      )}
    </div>
  );
}

/* ── Card records ─────────────────────────────────────────────────────── */

/**
 * Every card on file with where its figures came from. Manually entered
 * cards are shown as user-entered and unverified, and there is deliberately
 * no action here that could mark one bank-verified: no bank has confirmed it.
 */
export function AdminCardRecords() {
  const [kind, setKind] = useState('');
  const qs = `?per_page=100${kind ? `&kind=${kind}` : ''}`;
  const { data, loading, error, refetch } = useFetch(() => endpoints.admin.cardRecords(qs), [qs]);
  // counts sit beside data in the response, so the whole body is kept.
  const { data: counts } = useFetch(
    () => endpoints.admin.cardRecords('?per_page=1').then((body) => ({ data: body })), [],
  );

  if (error) return <Failed error={error} onRetry={refetch} />;
  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader title="Card records" subtitle="Tokenised cards carry a limit CashU set. Manual cards carry figures the customer typed." />
      <div className="grid grid-cols-2 gap-3 md:max-w-md">
        <StatCard label="Tokenised" value={counts?.counts?.tokenised ?? '—'} />
        <StatCard label="Manual (unverified)" value={counts?.counts?.manual ?? '—'} />
      </div>
      <Tabs
        className="max-w-md"
        tabs={[{ value: '', label: 'All' }, { value: 'TOKENISED', label: 'Tokenised' }, { value: 'MANUAL', label: 'Manual' }]}
        active={kind}
        onChange={setKind}
      />
      {loading && !data ? <Skeleton className="h-64 w-full rounded-2xl" /> : (
        <DataTable
          empty="No cards."
          rows={(data || []).map((c, i) => ({ ...c, id: i }))}
          columns={[
            { key: 'card', label: 'Card', render: (r) => <span>{r.issuer_bank} <span className="money text-slate">•• {r.last4}</span></span> },
            { key: 'customer', label: 'Customer', render: (r) => <span>{r.customer}<span className="money ml-1.5 text-2xs text-slate">{r.customer_phone}</span></span> },
            { key: 'source', label: 'Data source', render: (r) => <Badge tone={r.source === 'MANUAL' ? 'warn' : 'neutral'}>{r.source_label}</Badge> },
            { key: 'verification', label: 'Verification', render: (r) => <span className="text-xs text-slate">{r.verification}{r.is_test_card ? ' · test card' : ''}</span> },
            { key: 'limit', label: 'Limit', render: (r) => <span className="money">{r.credit_limit != null ? money(r.credit_limit) : '—'}</span> },
            { key: 'outstanding', label: 'Outstanding', render: (r) => <span className="money">{r.outstanding != null ? money(r.outstanding) : '—'}</span> },
            { key: 'status', label: 'Status' },
            { key: 'added', label: 'Added', render: (r) => dateTime(r.added_at) },
          ]}
        />
      )}
    </div>
  );
}
