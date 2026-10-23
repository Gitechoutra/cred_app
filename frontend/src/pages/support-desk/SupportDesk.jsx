import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import ConsoleShell from '../../components/layout/ConsoleShell';
import { IconHelp, IconHome, IconSearch, IconUser } from '../../components/layout/AppShell';
import TicketWorkspace, { TicketStatusBadge } from '../../components/support/TicketWorkspace';
import { Badge, Button, Card, Input, Skeleton, Tabs, cx } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { date, dateTime, money } from '../../utils/format';
import { AdminHeader, DataTable, StatCard } from '../admin/AdminLayout';

/**
 * The customer support desk portal, for L1 agents.
 *
 * Agents work tickets and look customers up. They see masked identity data
 * and the status of cards and payments; they cannot change a limit, approve
 * or refund anything, or see an MPIN, PAN or card number - the server has no
 * endpoint that would let them. Those decisions are escalated to an admin.
 */

const NAV = [
  { to: '/support-desk', end: true, label: 'Overview', icon: IconHome },
  { to: '/support-desk/tickets', label: 'Tickets', icon: IconHelp },
  { to: '/support-desk/customers', label: 'Customers', icon: IconUser },
];

export function SupportDeskLayout() {
  return <ConsoleShell nav={NAV} label="Support desk" accentClass="text-sky-700" />;
}

/* ── Overview ─────────────────────────────────────────────────────────── */

export function DeskOverview() {
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useFetch(() => endpoints.desk.overview(), []);

  if (loading && !data) return <Skeleton className="h-64 w-full rounded-2xl" />;
  if (error) {
    return (
      <Card className="text-center">
        <p className="font-semibold text-ink">Could not load the desk</p>
        <p className="mt-1 text-sm text-slate">{error.message}</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={refetch}>Try again</Button>
      </Card>
    );
  }

  const go = (query) => navigate(`/support-desk/tickets${query}`);
  return (
    <div className="animate-fade-up space-y-6">
      <AdminHeader
        title={`Hello, ${(data.agent?.full_name || 'there').split(' ')[0]}`}
        subtitle="Here is the queue right now."
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <button type="button" onClick={() => go('?assigned=me')} className="text-left">
          <StatCard label="Assigned to me" value={data.mine} hint="Open or in progress" />
        </button>
        <button type="button" onClick={() => go('?assigned=unassigned')} className="text-left">
          <StatCard label="Unassigned" value={data.unassigned} tone={data.unassigned ? 'alert' : 'neutral'} hint="Waiting for an agent" />
        </button>
        <button type="button" onClick={() => go('?status=OPEN')} className="text-left">
          <StatCard label="Open" value={data.open} />
        </button>
        <button type="button" onClick={() => go('?status=IN_PROGRESS')} className="text-left">
          <StatCard label="In progress" value={data.in_progress} hint={`${data.awaiting_agent} waiting on an agent`} />
        </button>
        <StatCard label="Escalated (open)" value={data.escalated} />
        <StatCard label="Resolved" value={data.resolved} tone="good" />
        <StatCard label="Closed" value={data.closed} />
      </div>
      <AgentLimits />
    </div>
  );
}

function AgentLimits({ items }) {
  const lines = items || [
    'No changes to credit limits, payments, refunds, KYC or account status - escalate those to an admin.',
    'No access to MPINs, full phone numbers, PAN, Aadhaar or card numbers.',
  ];
  return (
    <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4">
      <p className="text-sm font-semibold text-sky-900">What the desk can and cannot do</p>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-xs leading-relaxed text-sky-900/80">
        {lines.map((line) => <li key={line}>{line}</li>)}
      </ul>
    </div>
  );
}

/* ── Ticket queue ──────────────────────────────────────────────────────── */

export function DeskTickets() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get('status') || '';
  const assigned = params.get('assigned') || '';
  const escalated = params.get('escalated') === 'true';
  const [search, setSearch] = useState(params.get('q') || '');

  const query = new URLSearchParams();
  if (status) query.set('status', status);
  if (assigned) query.set('assigned', assigned);
  if (escalated) query.set('escalated', 'true');
  if (params.get('q')) query.set('q', params.get('q'));
  query.set('per_page', '50');
  const qs = `?${query.toString()}`;

  const { data, loading, error } = useFetch(() => endpoints.desk.tickets(qs), [qs]);

  const set = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader title="Tickets" subtitle="Newest activity first." />

      <Tabs
        className="max-w-xl"
        tabs={[
          { value: '', label: 'All' }, { value: 'OPEN', label: 'Open' },
          { value: 'IN_PROGRESS', label: 'In progress' }, { value: 'RESOLVED', label: 'Resolved' },
          { value: 'CLOSED', label: 'Closed' },
        ]}
        active={status}
        onChange={(value) => set('status', value)}
      />

      <div className="flex flex-wrap items-center gap-2">
        {[['', 'Anyone'], ['me', 'Mine'], ['unassigned', 'Unassigned']].map(([value, label]) => (
          <button
            key={label}
            type="button"
            onClick={() => set('assigned', value)}
            className={cx('rounded-full border px-3 py-1.5 text-xs font-semibold transition',
              assigned === value ? 'border-ink bg-ink text-white' : 'border-line text-slate hover:text-ink')}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => set('escalated', escalated ? '' : 'true')}
          className={cx('rounded-full border px-3 py-1.5 text-xs font-semibold transition',
            escalated ? 'border-alert bg-alert text-white' : 'border-line text-slate hover:text-ink')}
        >
          Escalated
        </button>
        <form
          className="ml-auto w-full sm:w-72"
          onSubmit={(e) => { e.preventDefault(); set('q', search.trim()); }}
        >
          <Input
            placeholder="Ticket number, subject or name"
            value={search}
            prefix={<IconSearch className="h-4 w-4" />}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
      </div>

      {error ? (
        <Card className="text-sm text-alert">{error.message}</Card>
      ) : loading && !data ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          empty="No tickets match these filters."
          rows={(data || []).map((t) => ({ ...t, id: t.ticket_id }))}
          onRowClick={(row) => navigate(`/support-desk/tickets/${row.ticket_id}`)}
          columns={[
            { key: 'ticket_number', label: 'Ticket', render: (r) => <span className="money font-semibold">{r.ticket_number}</span> },
            { key: 'subject', label: 'Subject', render: (r) => <span className="block max-w-[260px] truncate">{r.subject}</span> },
            { key: 'customer', label: 'Customer', render: (r) => (
              <span>{r.customer?.full_name || '—'}<span className="money ml-1.5 text-2xs text-slate">{r.customer?.phone_masked}</span></span>
            ) },
            { key: 'status', label: 'Status', render: (r) => <TicketStatusBadge ticket={r} /> },
            { key: 'priority', label: 'Priority', render: (r) => (
              <Badge tone={r.priority === 'HIGH' ? 'alert' : 'neutral'}>{r.priority?.toLowerCase()}</Badge>
            ) },
            { key: 'agent', label: 'Agent', render: (r) => r.assigned_agent_name || <span className="text-slate">Unassigned</span> },
            { key: 'updated', label: 'Updated', render: (r) => dateTime(r.updated_on) },
          ]}
        />
      )}
    </div>
  );
}

export function DeskTicket() {
  const { ticketId } = useParams();
  return (
    <TicketWorkspace
      ticketId={ticketId}
      backTo="/support-desk/tickets"
      customerPath={(id) => `/support-desk/customers/${id}`}
    />
  );
}

/* ── Customers ─────────────────────────────────────────────────────────── */

export function DeskCustomers() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function search(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await endpoints.desk.searchCustomers(q.trim());
      setResults(response.data || []);
    } catch (err) {
      setError(err.message);
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="animate-fade-up space-y-4">
      <AdminHeader
        title="Find a customer"
        subtitle="By full mobile number, email, customer id or ticket number. Every lookup is logged."
      />
      <form onSubmit={search} className="flex max-w-xl gap-2">
        <Input
          placeholder="9876543210, name@example.com, or CU2610231234"
          value={q}
          error={error}
          prefix={<IconSearch className="h-4 w-4" />}
          onChange={(e) => setQ(e.target.value)}
        />
        <Button type="submit" variant="mint" loading={loading} disabled={q.trim().length < 4} className="h-12 shrink-0">
          Search
        </Button>
      </form>

      {results && (
        <DataTable
          empty="No customer matches. Check the full number or email."
          rows={results.map((c) => ({ ...c, id: c.user_id }))}
          onRowClick={(row) => navigate(`/support-desk/customers/${row.user_id}`)}
          columns={[
            { key: 'full_name', label: 'Name', render: (r) => <span className="font-semibold">{r.full_name || '—'}</span> },
            { key: 'phone', label: 'Mobile', render: (r) => <span className="money">+91 {r.phone_masked}</span> },
            { key: 'email', label: 'Email', render: (r) => r.email_masked || '—' },
            { key: 'kyc', label: 'KYC', render: (r) => r.kyc_tier },
            { key: 'status', label: 'Account', render: (r) => <Badge tone={r.status === 'ACTIVE' ? 'good' : 'warn'}>{r.status}</Badge> },
          ]}
        />
      )}
    </div>
  );
}

export function DeskCustomer() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { data, loading, error } = useFetch(() => endpoints.desk.customer(userId), [userId]);

  if (loading && !data) return <Skeleton className="h-96 w-full rounded-2xl" />;
  if (error) return <Card className="text-sm text-alert">{error.message}</Card>;

  const { customer, cards, credit_line: credit, payments, tickets } = data;
  return (
    <div className="animate-fade-up space-y-5">
      <AdminHeader
        title={customer.full_name || 'Customer'}
        subtitle={`+91 ${customer.phone_masked} · ${customer.email_masked || 'no email'}${customer.email_verified ? ' (verified)' : ''}`}
        action={<Button variant="outline" size="sm" onClick={() => navigate('/support-desk/customers')}>New search</Button>}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Account" value={customer.status} />
        <StatCard label="KYC tier" value={customer.kyc_tier} />
        <StatCard label="Member since" value={date(customer.member_since)} />
        <StatCard label="Last sign-in" value={customer.last_login ? date(customer.last_login) : '—'} />
      </div>

      <AgentLimits items={data.agent_limits} />

      <section className="space-y-2">
        <h2 className="text-sm font-bold text-ink">Cards</h2>
        <DataTable
          empty="No cards."
          rows={cards.map((c, i) => ({ ...c, id: i }))}
          columns={[
            { key: 'bank', label: 'Card', render: (r) => <span>{r.issuer_bank} <span className="money text-slate">•• {r.last4}</span></span> },
            { key: 'network', label: 'Network' },
            { key: 'source', label: 'Data source', render: (r) => (
              <Badge tone={r.source === 'MANUAL' ? 'warn' : 'neutral'}>{r.source_label}</Badge>
            ) },
            { key: 'status', label: 'Status' },
            { key: 'linked', label: 'Added', render: (r) => date(r.linked_at) },
          ]}
        />
      </section>

      {credit && (
        <section className="space-y-2">
          <h2 className="text-sm font-bold text-ink">CashU credit line (read only)</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="Status" value={credit.status} />
            <StatCard label="Limit" value={money(credit.credit_limit)} />
            <StatCard label="Available" value={money(credit.available_credit)} />
            <StatCard label="Outstanding" value={money(credit.outstanding)} />
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-bold text-ink">Recent payments</h2>
        <DataTable
          empty="No payments yet."
          rows={payments.map((p, i) => ({ ...p, id: i }))}
          columns={[
            { key: 'kind', label: 'What' },
            { key: 'type', label: 'Type', render: (r) => (r.type || '').replace(/_/g, ' ').toLowerCase() },
            { key: 'amount', label: 'Amount', render: (r) => <span className="money">{money(r.amount)}</span> },
            { key: 'status', label: 'Status', render: (r) => (
              <Badge tone={/FAIL|CANCEL|REVERS|EXPIR/.test(r.status) ? 'alert' : /SUCC|SETTL/.test(r.status) ? 'good' : 'warn'}>{r.status}</Badge>
            ) },
            { key: 'reference', label: 'Reference', render: (r) => <span className="money text-xs">{r.reference}</span> },
            { key: 'at', label: 'When', render: (r) => dateTime(r.at) },
          ]}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-bold text-ink">Tickets</h2>
        <DataTable
          empty="No tickets."
          rows={tickets.map((t) => ({ ...t, id: t.ticket_id }))}
          onRowClick={(row) => navigate(`/support-desk/tickets/${row.ticket_id}`)}
          columns={[
            { key: 'ticket_number', label: 'Ticket', render: (r) => <span className="money font-semibold">{r.ticket_number}</span> },
            { key: 'subject', label: 'Subject' },
            { key: 'status', label: 'Status', render: (r) => <TicketStatusBadge ticket={r} /> },
            { key: 'created', label: 'Raised', render: (r) => date(r.created_on) },
          ]}
        />
      </section>
    </div>
  );
}
