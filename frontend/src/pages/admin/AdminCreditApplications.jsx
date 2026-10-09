import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Row, Skeleton, Tabs, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useBack } from '../../hooks/useNavHistory';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { dateTime, money } from '../../utils/format';
import { AdminHeader, DataTable } from './AdminLayout';
import KycDocumentViewer, { AuthenticityGate } from './KycDocumentViewer';

/**
 * Credit applications: the queue, and the full review of one application.
 *
 * The reviewer decides *whether*, never *how much*. The eligible limit is
 * worked out on the server from verified income and the credit bureau score,
 * and approving grants exactly that; there is no amount to type. What this
 * screen owes the reviewer is everything behind that number - identity and its
 * documents, employment, the income proof, the bank account and how it was
 * verified, the bureau result, and each eligibility rule with its outcome - so
 * the decision is made on evidence rather than on a figure taken on trust.
 */

const DECIDERS = ['L2_RISK_RECON', 'L3_SUPER_ADMIN'];

const STATUS_TONE = {
  KYC_PENDING: 'warn',
  UNDER_REVIEW: 'warn',
  APPROVED: 'good',
  REJECTED: 'alert',
  WITHDRAWN: 'neutral',
};

const STATUS_LABEL = {
  KYC_PENDING: 'Awaiting KYC',
  UNDER_REVIEW: 'Ready for review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
};

function StatusBadge({ status }) {
  return <Badge tone={STATUS_TONE[status] || 'neutral'} dot>{STATUS_LABEL[status] || status}</Badge>;
}

function titleCase(value) {
  return (value || '').replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

/* ── Queue ──────────────────────────────────────────────────────────────── */

export default function AdminCreditApplications() {
  const navigate = useNavigate();
  const [tab, setTab] = useState('OPEN');
  const [state, setState] = useState({ rows: null, counts: {}, error: null });

  const load = useCallback(async () => {
    try {
      const response = await endpoints.admin.creditApplications(`?status=${tab}&per_page=100`);
      setState({ rows: response.data || [], counts: response.counts || {}, error: null });
    } catch (err) {
      setState((current) => ({ ...current, rows: [], error: err }));
    }
  }, [tab]);

  useEffect(() => {
    setState((current) => ({ ...current, rows: null }));
    load();
  }, [load]);

  const { rows, counts } = state;

  const columns = [
    {
      key: 'applicant',
      label: 'Applicant',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{row.full_name || '—'}</p>
          <p className="money text-2xs text-slate">{row.phone}</p>
        </div>
      ),
    },
    {
      key: 'employment',
      label: 'Employment',
      render: (row) => (
        <div>
          <p className="text-ink">{titleCase(row.employment_type)}</p>
          {row.employer_name && <p className="max-w-[180px] truncate text-2xs text-slate">{row.employer_name}</p>}
        </div>
      ),
    },
    {
      key: 'income',
      label: 'Income / EMIs',
      render: (row) => (
        <div className="money">
          <p className="text-ink">{money(row.monthly_income, { decimals: 0 })}</p>
          <p className="text-2xs text-slate">{money(row.existing_emi_outflow, { decimals: 0 })} EMIs</p>
        </div>
      ),
    },
    {
      key: 'score',
      label: 'Credit score',
      render: (row) => (
        row.credit_no_history ? (
          <div>
            <p className="font-semibold text-ink">Not Available</p>
            <Badge tone="neutral">New to credit</Badge>
          </div>
        ) : row.credit_score != null ? (
          <div>
            <p className="money font-semibold text-ink">{row.credit_score}</p>
            <p className="text-2xs text-slate">{row.credit_score_band}</p>
          </div>
        ) : row.credit_status === 'UNAVAILABLE'
          ? <Badge tone="warn">{row.credit_status_label}</Badge>
          : <span className="text-slate">—</span>
      ),
    },
    {
      key: 'limit',
      label: tab === 'APPROVED' ? 'Approved limit' : 'Eligible limit',
      render: (row) => {
        const amount = tab === 'APPROVED' ? row.approved_limit : row.eligible_limit;
        if (amount) return <span className="money font-semibold text-ink">{money(amount, { decimals: 0 })}</span>;
        if (row.status === 'KYC_PENDING') return <span className="text-2xs text-slate">After KYC</span>;
        if (row.assessment_reason) return <Badge tone="alert">Not eligible</Badge>;
        return <span className="text-slate">—</span>;
      },
    },
    {
      key: 'when',
      label: rows && tab !== 'OPEN' && tab !== 'UNDER_REVIEW' && tab !== 'KYC_PENDING' ? 'Decided' : 'Waiting',
      render: (row) => (
        row.waiting_hours != null ? (
          <span className={cx('money text-sm', row.waiting_hours > 24 ? 'font-semibold text-alert' : 'text-slate')}>
            {row.waiting_hours}h
          </span>
        ) : <span className="text-2xs text-slate">{row.decided_at ? dateTime(row.decided_at) : '—'}</span>
      ),
    },
    { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div>
      <AdminHeader
        title="Credit applications"
        subtitle="Review the complete application, then approve or reject the eligible limit."
      />

      <Tabs
        className="mb-4 max-w-3xl overflow-x-auto"
        active={tab}
        onChange={setTab}
        tabs={[
          { value: 'OPEN', label: 'Open', count: counts.open },
          { value: 'UNDER_REVIEW', label: 'Ready', count: counts.UNDER_REVIEW },
          { value: 'KYC_PENDING', label: 'Awaiting KYC', count: counts.KYC_PENDING },
          { value: 'APPROVED', label: 'Approved', count: counts.APPROVED },
          { value: 'REJECTED', label: 'Rejected', count: counts.REJECTED },
          { value: 'WITHDRAWN', label: 'Withdrawn', count: counts.WITHDRAWN },
        ]}
      />

      {rows === null ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          columns={columns}
          rows={rows.map((row) => ({ ...row, id: row.application_id }))}
          empty={tab === 'OPEN' ? 'No applications are waiting. Nice.' : 'Nothing here yet.'}
          onRowClick={(row) => navigate(`/admin/credit/${row.application_id}`)}
        />
      )}
    </div>
  );
}

/* ── One application ────────────────────────────────────────────────────── */

export function AdminCreditApplicationReview() {
  const { applicationId } = useParams();
  const back = useBack('/admin/credit');
  const toast = useToast();
  const { role } = useProfile();

  const { data: app, loading, error, refetch } = useFetch(
    () => endpoints.admin.creditApplication(applicationId), [applicationId],
  );

  const [note, setNote] = useState('');
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState('');

  const [kycVerified, setKycVerified] = useState(false);
  const [kycReason, setKycReason] = useState('');

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  if (!app) {
    return (
      <Card className="p-8 text-center">
        <p className="font-semibold text-ink">{error?.status === 404 ? 'Application not found' : 'Could not load this application'}</p>
        <p className="mt-1 text-sm text-slate">{error?.message}</p>
        <Button variant="outline" className="mt-4" onClick={back}>Back to the queue</Button>
      </Card>
    );
  }

  const canDecide = app.can_decide && DECIDERS.includes(role);
  const kyc = app.kyc || {};
  const kycOpen = ['PENDING', 'UNDER_REVIEW'].includes(kyc.kyc_status);
  // The server sets an eligible limit only when every rule passes.
  const eligible = Boolean(app.eligible_limit);
  const ready = app.status === 'UNDER_REVIEW';
  const breakdown = app.eligibility_breakdown;

  async function decide(decision) {
    if (decision === 'REJECT' && !note.trim()) {
      toast.error('Give the applicant a reason when rejecting.');
      return;
    }
    setBusy(decision);
    try {
      const response = await endpoints.admin.reviewCreditApplication(applicationId, {
        decision, note: note.trim() || undefined,
      });
      toast.success(response.message);
      setNote('');
      setChecked(false);
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy('');
    }
  }

  async function reviewKyc(decision) {
    if (decision === 'REJECT' && !kycReason.trim()) {
      toast.error('A reason is required to reject KYC.');
      return;
    }
    setBusy(`KYC_${decision}`);
    try {
      const response = await endpoints.admin.reviewKyc(kyc.kyc_id, {
        decision,
        tier: decision === 'APPROVE'
          ? (kyc.requested_tier === 'FULL' && kyc.aadhaar_masked ? 'FULL' : 'MINIMUM')
          : undefined,
        reason: kycReason.trim() || undefined,
      });
      toast.success(response.message);
      setKycReason('');
      setKycVerified(false);
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <div>
      <AdminHeader
        title={app.applicant?.full_name || 'Credit application'}
        subtitle={`Application ${app.application_id.slice(0, 8).toUpperCase()} · submitted ${dateTime(app.submitted_at)}`}
        action={(
          <div className="flex items-center gap-2">
            <StatusBadge status={app.status} />
            <Button variant="outline" size="sm" onClick={back}>Back</Button>
          </div>
        )}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* ── Evidence ─────────────────────────────────────────────── */}
        <div className="space-y-4">
          <Panel title="Applicant">
            <div className="grid gap-x-6 sm:grid-cols-2">
              <Row label="Name" value={app.applicant?.full_name} />
              <Row label="Phone" value={app.applicant?.phone} mono />
              <Row label="Account status" value={titleCase(app.applicant?.status)} />
              <Row label="Member since" value={dateTime(app.applicant?.member_since)} />
            </div>
          </Panel>

          <Panel
            title="Identity (KYC)"
            badge={<Badge tone={kyc.kyc_status === 'APPROVED' ? 'good' : kycOpen ? 'warn' : 'alert'} dot>
              {kyc.kyc_status === 'APPROVED' ? `${app.applicant?.kyc_tier} verified` : titleCase(kyc.kyc_status)}
            </Badge>}
          >
            <div className="grid gap-x-6 sm:grid-cols-2">
              <Row label="Legal name" value={kyc.verified_legal_name || '—'} />
              <Row label="PAN" value={kyc.pan_masked || '—'} mono />
              <Row label="Aadhaar" value={kyc.aadhaar_masked || 'Not given'} mono />
              <Row label="Requested level" value={kyc.requested_tier || '—'} />
            </div>
            {kyc.rejection_reason && (
              <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-alert">Rejected: {kyc.rejection_reason}</p>
            )}
            {app.can_view_documents ? (
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                {(kyc.documents || []).map((doc) => (
                  <KycDocumentViewer
                    key={doc.slot}
                    kycId={kyc.kyc_id}
                    slot={doc.slot}
                    label={doc.label}
                    available={doc.available}
                  />
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate">Documents are visible to L2 Risk and L3 Super Admin only.</p>
            )}

            {kycOpen && canDecideKyc(role) && (
              <div className="mt-4 space-y-3 rounded-2xl border border-amber-200 bg-amber-50/40 p-4">
                <p className="text-sm font-semibold text-ink">KYC is waiting for verification</p>
                <p className="text-xs text-slate">
                  Verifying it here moves the application to review and fetches the
                  credit score from the bureau.
                </p>
                <AuthenticityGate checked={kycVerified} onChange={setKycVerified} />
                <textarea
                  rows={2}
                  value={kycReason}
                  onChange={(event) => setKycReason(event.target.value)}
                  placeholder="Reason, if rejecting KYC - shown to the applicant."
                  className="w-full rounded-xl border border-line bg-canvas p-3 text-sm outline-none focus:border-ink/40"
                />
                <div className="flex gap-2">
                  <Button variant="danger" full loading={busy === 'KYC_REJECT'} onClick={() => reviewKyc('REJECT')}>
                    Reject KYC
                  </Button>
                  <Button variant="mint" full disabled={!kycVerified} loading={busy === 'KYC_APPROVE'} onClick={() => reviewKyc('APPROVE')}>
                    Verify KYC
                  </Button>
                </div>
              </div>
            )}
          </Panel>

          <Panel title="Employment and income">
            <div className="grid gap-x-6 sm:grid-cols-2">
              <Row label="Employment" value={titleCase(app.employment_type)} />
              <Row label={app.employment_type === 'SELF_EMPLOYED' ? 'Business' : 'Employer'} value={app.employer_name || '—'} />
              <Row label="Designation" value={app.designation || '—'} />
              <Row label="In current job" value={app.months_in_current_job != null ? `${app.months_in_current_job} months` : '—'} />
              <Row label="Monthly income" value={money(app.monthly_income)} mono />
              <Row label="Existing EMIs" value={money(app.existing_emi_outflow)} mono />
            </div>
            <div className="mt-4">
              <p className="mb-2 text-2xs font-bold uppercase tracking-[0.12em] text-slate">
                Income proof · {app.income_proof?.label || 'Not given'}
              </p>
              {app.can_view_documents ? (
                <KycDocumentViewer
                  label={app.income_proof?.label || 'Income proof'}
                  available={Boolean(app.income_proof?.available)}
                  load={() => endpoints.admin.incomeProofUrl(app.application_id)}
                  docKey={app.application_id}
                />
              ) : (
                <p className="text-xs text-slate">Documents are visible to L2 Risk and L3 Super Admin only.</p>
              )}
            </div>
          </Panel>

          <Panel
            title="Salary bank account"
            badge={app.bank_account && (
              <Badge tone={app.bank_account.penny_drop_status === 'VERIFIED' ? 'good' : 'warn'} dot>
                {app.bank_account.penny_drop_status === 'VERIFIED' ? 'Penny drop verified' : titleCase(app.bank_account.penny_drop_status)}
              </Badge>
            )}
          >
            {app.bank_account ? (
              <div className="grid gap-x-6 sm:grid-cols-2">
                <Row label="Bank" value={app.bank_account.bank_name || '—'} />
                <Row label="Account" value={app.bank_account.masked_account} mono />
                <Row label="IFSC" value={app.bank_account.ifsc_code} mono />
                <Row label="Type" value={titleCase(app.bank_account.account_type)} />
                <Row label="Name at bank" value={app.bank_account.verified_cbs_name || '—'} />
                <Row
                  label="Name match"
                  value={app.bank_account.name_match_score != null ? `${app.bank_account.name_match_score}%` : '—'}
                  mono
                />
              </div>
            ) : <p className="text-sm text-slate">No bank account on this application.</p>}
          </Panel>
        </div>

        {/* ── Decision ─────────────────────────────────────────────── */}
        <div className="space-y-4 xl:sticky xl:top-20 xl:self-start">
          <Panel title="Credit bureau">
            <div className="flex items-end justify-between">
              <div>
                <p className={cx('font-bold text-ink', app.bureau?.credit_score != null ? 'money text-4xl' : 'text-2xl')}>
                  {app.bureau?.credit_score ?? (app.bureau?.status === 'PENDING' ? '—' : 'Not Available')}
                </p>
                <p className="mt-1 text-xs text-slate">
                  {app.bureau?.no_history
                    ? `${app.bureau.status_label}${app.bureau.bureau_code ? ` (bureau: ${app.bureau.bureau_code})` : ''}`
                    : app.bureau?.status === 'SCORED' ? app.bureau.score_band
                      : app.bureau?.status === 'UNAVAILABLE' ? `${app.bureau.status_label}: ${app.bureau.error}`
                        : (app.status === 'KYC_PENDING' ? 'Fetched once KYC is verified' : 'Not fetched')}
                </p>
                {app.bureau?.is_demo && (
                  <Badge tone="warn" className="mt-1">
                    {app.bureau.provider === 'SANDBOX' ? 'Sandbox bureau' : 'Test environment'}
                  </Badge>
                )}
              </div>
              {app.bureau?.credit_score != null && <ScoreBar score={app.bureau.credit_score} />}
            </div>
            <div className="mt-3 border-t border-line pt-1">
              {app.bureau?.bureau && <Row label="Bureau" value={app.bureau.bureau} />}
              <Row label="Consent given" value={dateTime(app.bureau?.consented_at) || '—'} />
              <Row label="Fetched" value={dateTime(app.bureau?.fetched_at) || '—'} />
              {app.bureau?.reference && <Row label="Reference" value={app.bureau.reference} mono />}
            </div>
          </Panel>

          {app.is_open ? (
            <Panel title="Eligibility">
              <div className={cx('rounded-2xl p-4', app.eligible_limit ? 'bg-ink text-white' : 'bg-mist')}>
                <p className={cx('text-2xs uppercase tracking-wider', app.eligible_limit ? 'text-white/60' : 'text-slate')}>
                  Eligible limit
                </p>
                <p className={cx('money mt-1 text-3xl font-bold', app.eligible_limit ? 'text-mint' : 'text-ink')}>
                  {app.eligible_limit ? money(app.eligible_limit, { decimals: 0 }) : 'Not eligible'}
                </p>
                {app.assessment_message && <p className="mt-1 text-xs text-slate">{app.assessment_message}</p>}
              </div>

              {app.eligibility_checks?.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {app.eligibility_checks.map((item) => (
                    <li key={item.key} className="flex items-start gap-2 text-xs">
                      <span className={cx('mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] font-bold',
                        item.passed ? 'bg-mint text-ink' : 'bg-alert text-white')}
                      >
                        {item.passed ? '✓' : '✕'}
                      </span>
                      <span>
                        <span className="font-medium text-ink">{item.label}</span>
                        <span className="block text-slate">{item.detail}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {breakdown && (
                <div className="mt-3 border-t border-line pt-1">
                  <Row label="Disposable income" value={money(breakdown.disposable_income)} mono />
                  <Row label="EMIs / income (FOIR)" value={`${breakdown.foir_percent}% of ${breakdown.max_foir_percent}%`} mono />
                  {breakdown.income_multiple != null && (
                    <Row label="Score multiple" value={`${breakdown.income_multiple}× monthly`} mono />
                  )}
                  {breakdown.base_limit != null && <Row label="Before caps" value={money(breakdown.base_limit, { decimals: 0 })} mono />}
                  {breakdown.thin_file_cap != null && <Row label="Thin-file cap" value={money(breakdown.thin_file_cap, { decimals: 0 })} mono />}
                  {breakdown.kyc_cap != null && <Row label={`${breakdown.kyc_tier} KYC cap`} value={money(breakdown.kyc_cap, { decimals: 0 })} mono />}
                </div>
              )}
            </Panel>
          ) : (
            <Panel title="Decision">
              <div className={cx('rounded-2xl p-4', app.status === 'APPROVED' ? 'bg-mint-50' : 'bg-red-50')}>
                <p className="text-sm font-semibold text-ink">{STATUS_LABEL[app.status]}</p>
                {app.approved_limit > 0 && (
                  <p className="money mt-1 text-2xl font-bold text-ink">{money(app.approved_limit, { decimals: 0 })}</p>
                )}
                <p className="mt-1 text-xs text-slate">{app.decision_note || app.decision_message}</p>
              </div>
              <Row label="Decided" value={dateTime(app.decided_at) || '—'} />
            </Panel>
          )}

          {app.is_open && (
            <Panel title="Decision">
              {!canDecide ? (
                <p className="text-xs text-slate">Approving or rejecting needs L2 Risk or L3 Super Admin access.</p>
              ) : (
                <div className="space-y-3">
                  {!ready && (
                    <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      Verify the applicant's KYC before this can be approved. It can be rejected now.
                    </p>
                  )}
                  {ready && eligible && (
                    <label className={cx('flex cursor-pointer items-start gap-3 rounded-xl border p-3',
                      checked ? 'border-mint bg-mint-50' : 'border-line')}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => setChecked(event.target.checked)}
                        className="mt-0.5 h-4 w-4 accent-mint"
                      />
                      <span className="text-xs leading-relaxed text-slate">
                        I have checked the income proof against the declared income and
                        the bank account, and approve a limit of{' '}
                        <span className="money font-semibold text-ink">{money(app.eligible_limit, { decimals: 0 })}</span>.
                      </span>
                    </label>
                  )}
                  <textarea
                    rows={3}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Note - required to reject, and shown to the applicant."
                    className="w-full rounded-xl border border-line bg-canvas p-3 text-sm outline-none focus:border-ink/40"
                  />
                  <div className="flex gap-2">
                    <Button variant="danger" full loading={busy === 'REJECT'} onClick={() => decide('REJECT')}>
                      Reject
                    </Button>
                    <Button
                      variant="mint"
                      full
                      disabled={!ready || !eligible || !checked}
                      loading={busy === 'APPROVE'}
                      onClick={() => decide('APPROVE')}
                    >
                      Approve
                    </Button>
                  </div>
                  <p className="text-2xs leading-relaxed text-slate">
                    Approval issues the credit line at the eligible limit. The applicant
                    then chooses a purpose and activates it. Recorded against your account.
                  </p>
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function canDecideKyc(role) {
  return DECIDERS.includes(role);
}

function Panel({ title, badge, children }) {
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-2xs font-bold uppercase tracking-[0.12em] text-slate">{title}</h2>
        {badge}
      </div>
      {children}
    </Card>
  );
}

/** Where a score sits on the 300-900 bureau scale. */
function ScoreBar({ score }) {
  const at = Math.max(0, Math.min(100, ((score - 300) / 600) * 100));
  return (
    <div className="w-32">
      <div className="relative h-2 rounded-full bg-gradient-to-r from-red-400 via-amber-300 to-mint">
        <span
          className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded bg-ink"
          style={{ left: `${at}%` }}
        />
      </div>
      <div className="money mt-1 flex justify-between text-[10px] text-slate">
        <span>300</span><span>900</span>
      </div>
    </div>
  );
}
