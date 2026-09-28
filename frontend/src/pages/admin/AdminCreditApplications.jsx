import { useCallback, useEffect, useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Row, Sheet, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useProfile } from '../../hooks/useProfile';
import { dateTime, money } from '../../utils/format';
import { AdminHeader, DataTable } from './AdminLayout';

/**
 * Credit applications, for review.
 *
 * Applications used to reach the database and stop there: the approve and
 * reject endpoints existed, but no screen in the admin portal called them, so
 * nobody could see an application, let alone decide it.
 *
 * The limit is not a field here. It is worked out from the applicant's salary
 * and credit score, and approval grants exactly that. The reviewer decides
 * whether to lend, not how much - and cannot approve an application the rules
 * found ineligible, only reject it with a reason.
 *
 * L1 support can read the queue; deciding needs L2 risk or L3.
 */

const TABS = [
  { value: 'OPEN', label: 'Open', count: 'open' },
  { value: 'APPROVED', label: 'Approved', count: 'APPROVED' },
  { value: 'REJECTED', label: 'Rejected', count: 'REJECTED' },
  { value: 'WITHDRAWN', label: 'Withdrawn', count: 'WITHDRAWN' },
];

const STATUS = {
  UNDER_REVIEW: { label: 'Under review', tone: 'warn' },
  KYC_PENDING: { label: 'Waiting for KYC', tone: 'neutral' },
  APPROVED: { label: 'Approved', tone: 'good' },
  REJECTED: { label: 'Rejected', tone: 'alert' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'neutral' },
};

function scoreTone(score) {
  if (score == null) return 'neutral';
  if (score >= 750) return 'good';
  if (score >= 650) return 'warn';
  return 'alert';
}

function Score({ row }) {
  if (row.credit_no_history) return <Badge tone="neutral">No history</Badge>;
  if (row.credit_score == null) {
    return <span className="text-2xs text-slate">{row.status === 'KYC_PENDING' ? 'After KYC' : 'Unavailable'}</span>;
  }
  return (
    <div className="flex items-center gap-2">
      <span className="money text-sm font-bold text-ink">{row.credit_score}</span>
      <Badge tone={scoreTone(row.credit_score)}>{row.credit_score_band}</Badge>
    </div>
  );
}

export default function AdminCreditApplications() {
  const toast = useToast();
  const { role } = useProfile();
  const canDecide = ['L2_RISK_RECON', 'L3_SUPER_ADMIN'].includes(role);

  const [tab, setTab] = useState('OPEN');
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ rows: [], counts: {}, pagination: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [selected, setSelected] = useState(null);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await endpoints.admin.creditApplications(
        `?status=${tab}&page=${page}&per_page=20`,
      );
      setData({
        rows: response.data || [],
        counts: response.counts || {},
        pagination: response.pagination,
      });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [tab, page]);

  useEffect(() => { load(); }, [load]);

  function close() {
    setSelected(null);
    setRejecting(false);
    setNote('');
  }

  async function decide(decision) {
    if (decision === 'REJECT' && !note.trim()) {
      toast.error('Give a reason for the rejection. The applicant sees it.');
      return;
    }
    setBusy(true);
    try {
      const response = await endpoints.admin.reviewCreditApplication(
        selected.application_id,
        { decision, note: note.trim() || undefined },
      );
      toast.success(response.message);
      close();
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  const columns = [
    {
      key: 'applicant',
      label: 'Applicant',
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-ink">{row.full_name || '—'}</p>
          <p className="money text-2xs text-slate">{row.phone} · {row.kyc_tier} KYC</p>
        </div>
      ),
    },
    {
      key: 'salary',
      label: 'Monthly salary',
      render: (row) => (
        <div>
          <p className="money font-medium text-ink">{money(row.monthly_income, { decimals: 0 })}</p>
          {row.existing_emi_outflow > 0 && (
            <p className="money text-2xs text-slate">EMIs {money(row.existing_emi_outflow, { decimals: 0 })}</p>
          )}
        </div>
      ),
    },
    { key: 'score', label: 'CIBIL score', render: (row) => <Score row={row} /> },
    {
      key: 'limit',
      label: tab === 'APPROVED' ? 'Approved limit' : 'Eligible limit',
      render: (row) => {
        const value = tab === 'APPROVED' ? row.approved_limit : row.eligible_limit;
        if (value) return <span className="money font-semibold text-ink">{money(value, { decimals: 0 })}</span>;
        if (row.assessment_message) return <span className="text-2xs text-alert">Not eligible</span>;
        return <span className="text-2xs text-slate">—</span>;
      },
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => {
        const meta = STATUS[row.status] || { label: row.status, tone: 'neutral' };
        return <Badge tone={meta.tone} dot>{meta.label}</Badge>;
      },
    },
    {
      key: 'when',
      label: tab === 'OPEN' ? 'Waiting' : 'Decided',
      render: (row) => (
        <span className="whitespace-nowrap text-2xs text-slate">
          {tab === 'OPEN'
            ? (row.waiting_hours != null ? `${row.waiting_hours} h` : '—')
            : dateTime(row.decided_at)}
        </span>
      ),
    },
  ];

  const pagination = data.pagination;

  return (
    <div>
      <AdminHeader
        title="Credit applications"
        subtitle="Limits are worked out from salary and CIBIL score. Approve or reject each one."
        action={<Button variant="outline" size="sm" onClick={load}>Refresh</Button>}
      />

      <div className="mb-4 flex flex-wrap gap-2" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={tab === item.value}
            onClick={() => { setTab(item.value); setPage(1); }}
            className={cx(
              'rounded-full border px-3.5 py-1.5 text-xs font-semibold transition',
              tab === item.value
                ? 'border-ink bg-ink text-white'
                : 'border-line bg-canvas text-slate hover:text-ink',
            )}
          >
            {item.label}
            <span className="money ml-1.5 opacity-70">{data.counts[item.count] ?? 0}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full" />)}
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-alert">{error.message}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={load}>Try again</Button>
        </div>
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data.rows}
            empty={tab === 'OPEN' ? 'No applications waiting. New ones appear here as soon as they are submitted.' : 'Nothing here yet.'}
            onRowClick={(row) => setSelected(row)}
          />
          {pagination && pagination.pages > 1 && (
            <div className="mt-4 flex items-center justify-between text-xs text-slate">
              <span>Page {pagination.page} of {pagination.pages} · {pagination.total} applications</span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={!pagination.has_prev} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" disabled={!pagination.has_next} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}

      <Sheet
        open={Boolean(selected)}
        onClose={close}
        title={selected?.full_name || 'Application'}
        footer={selected && canDecide && selected.status === 'UNDER_REVIEW' && (
          rejecting ? (
            <div className="flex gap-2">
              <Button variant="outline" size="lg" full onClick={() => setRejecting(false)}>Back</Button>
              <Button variant="danger" size="lg" full loading={busy} onClick={() => decide('REJECT')}>Reject</Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Button variant="outline" size="lg" full onClick={() => setRejecting(true)}>Reject</Button>
              <Button
                variant="mint"
                size="lg"
                full
                loading={busy}
                disabled={!selected.eligible}
                onClick={() => decide('APPROVE')}
              >
                {selected.eligible ? `Approve ${money(selected.eligible_limit, { decimals: 0 })}` : 'Not eligible'}
              </Button>
            </div>
          )
        )}
      >
        {selected && (
          <div className="space-y-4 pb-2">
            <div className="rounded-2xl bg-gradient-to-br from-ink to-[#0f1a1f] p-4 text-white">
              <p className="text-2xs font-semibold uppercase tracking-wider text-white/60">
                {selected.status === 'APPROVED' ? 'Approved limit' : 'Eligible limit'}
              </p>
              <p className="money mt-1 text-3xl font-bold">
                {(selected.status === 'APPROVED' ? selected.approved_limit : selected.eligible_limit)
                  ? money(selected.status === 'APPROVED' ? selected.approved_limit : selected.eligible_limit, { decimals: 0 })
                  : 'Not eligible'}
              </p>
              <p className="mt-1 text-2xs text-white/60">
                Worked out from salary and CIBIL score. It cannot be changed here.
              </p>
            </div>

            {selected.assessment_message && (
              <p className="rounded-xl bg-red-50 px-3.5 py-3 text-xs text-alert">{selected.assessment_message}</p>
            )}
            {selected.full_kyc_limit > 0 && (
              <p className="rounded-xl bg-amber-50 px-3.5 py-3 text-xs text-amber-800">
                Capped by minimum KYC. With full KYC this applicant would be eligible for
                {' '}<span className="money font-semibold">{money(selected.full_kyc_limit, { decimals: 0 })}</span>.
              </p>
            )}

            <div className="divide-y divide-line">
              <Row label="Status" value={(STATUS[selected.status] || {}).label || selected.status} />
              <Row label="CIBIL score" value={<Score row={selected} />} />
              <Row label="Monthly salary" value={money(selected.monthly_income)} mono />
              <Row label="Existing EMIs" value={money(selected.existing_emi_outflow)} mono />
              <Row label="Employment" value={selected.employment_type?.replace(/_/g, ' ').toLowerCase()} />
              <Row label="KYC" value={selected.kyc_tier} />
              <Row label="Phone" value={selected.phone} mono />
              <Row label="Submitted" value={dateTime(selected.submitted_at)} />
              {selected.decided_at && <Row label="Decided" value={dateTime(selected.decided_at)} />}
              {selected.decision_note && <Row label="Reason given" value={selected.decision_note} />}
            </div>

            {selected.status === 'KYC_PENDING' && (
              <p className="rounded-xl bg-mist px-3.5 py-3 text-xs text-slate">
                Waiting for the applicant&rsquo;s KYC. The credit score is fetched and the
                limit worked out as soon as it is approved, and the application moves to
                Under review by itself.
              </p>
            )}
            {!canDecide && selected.status === 'UNDER_REVIEW' && (
              <p className="rounded-xl bg-mist px-3.5 py-3 text-xs text-slate">
                Deciding needs the Risk or Super Admin role.
              </p>
            )}

            {rejecting && (
              <div className="animate-slide-down">
                <label htmlFor="reject-note" className="mb-1.5 block text-sm font-medium text-ink">
                  Reason for rejecting
                </label>
                <textarea
                  id="reject-note"
                  rows={3}
                  value={note}
                  maxLength={500}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="The applicant sees this."
                  className="w-full rounded-xl border border-line px-3.5 py-2.5 text-sm text-ink outline-none focus:border-ink/40 focus:ring-2 focus:ring-mint/20"
                  autoFocus
                />
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  );
}
