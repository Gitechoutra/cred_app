import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Timeline } from '../../components/domain';
import { Badge, Button, Card, Row, Sheet, Skeleton, cx } from '../../components/ui';
import {
  ErrorCard, JourneySteps, StatusHero, friendlyError,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Where an application stands.
 *
 * The state machine is rendered as a sequence of things that have happened,
 * because "UNDER_REVIEW" tells somebody waiting on a credit decision nothing
 * they can act on. Each step says what it was and when, and the current one
 * says what happens next.
 *
 * While undecided the screen checks back quietly, so an approval appears
 * without the applicant having to know to refresh. The KYC step shows the
 * verification's own state - not submitted, being reviewed, or rejected with
 * the reason - because "complete your KYC" is the wrong instruction for someone
 * whose documents are already with a reviewer.
 *
 * The rejection path gets the same care as the approval path. A decline is the
 * outcome people most need explained, and the reason comes from the server as a
 * code with wording attached, so the same decision always reads the same way.
 */

const POLL_EVERY_MS = 15000;
const OPEN = ['KYC_PENDING', 'UNDER_REVIEW'];

function kycDetail(kyc) {
  switch (kyc?.kyc_status) {
    case 'PENDING':
    case 'UNDER_REVIEW':
      return { text: 'Documents received - being reviewed', tone: 'warn' };
    case 'REJECTED':
      return {
        text: kyc.rejection_reason
          ? `Not approved: ${kyc.rejection_reason}`
          : 'Not approved - please submit again',
        tone: 'alert',
      };
    case 'EXPIRED':
      return { text: 'Expired - please submit again', tone: 'alert' };
    default:
      return { text: 'Complete your KYC to continue', tone: 'warn' };
  }
}

function buildTimeline(application, kyc, account) {
  const status = application.status;
  const rejected = status === 'REJECTED';
  const withdrawn = status === 'WITHDRAWN';
  const approved = status === 'APPROVED';
  const kycState = kycDetail(kyc);
  // The bureau's answer as the backend reports it: SCORED, NO_HISTORY,
  // UNAVAILABLE or PENDING. Nothing here works out a score or a status.
  const bureau = application.credit_status;
  const scored = bureau === 'SCORED' || bureau === 'NO_HISTORY';
  const active = account?.status === 'ACTIVE';

  return [
    {
      label: 'Application received',
      detail: application.submitted_at ? date(application.submitted_at) : null,
      done: true,
    },
    {
      label: 'Identity verified',
      detail: application.kyc_verified_at ? date(application.kyc_verified_at) : kycState.text,
      done: Boolean(application.kyc_verified_at),
      current: status === 'KYC_PENDING',
      failed: status === 'KYC_PENDING' && kycState.tone === 'alert',
    },
    {
      label: 'Credit check and eligibility',
      detail: scored
        ? [
          bureau === 'NO_HISTORY'
            ? `Credit score: Not Available · ${application.credit_status_label}`
            : `Credit score ${application.credit_score} (${application.credit_score_band})`,
          application.eligible_limit ? `eligible for ${money(application.eligible_limit, { decimals: 0 })}, subject to review` : null,
        ].filter(Boolean).join(' · ')
        : bureau === 'UNAVAILABLE'
          ? `Credit score: Not Available · ${application.credit_status_label} - we will try the bureau again before review`
          : (application.kyc_verified_at ? 'Fetching your credit score' : 'After identity is verified'),
      done: scored || approved || rejected,
      current: bureau === 'UNAVAILABLE' && !approved && !rejected,
    },
    {
      label: 'Reviewed by our credit team',
      detail: status === 'UNDER_REVIEW'
        ? 'Usually within one working day'
        : (application.decided_at ? date(application.decided_at) : null),
      done: approved || rejected,
      current: status === 'UNDER_REVIEW',
    },
    {
      label: rejected ? 'Not approved' : withdrawn ? 'Withdrawn' : 'Approved',
      detail: rejected
        ? (application.decision_note || application.decision_message)
        : (application.approved_limit ? `${money(application.approved_limit)} credit limit` : null),
      done: approved || rejected,
      current: approved && !active,
      failed: rejected || withdrawn,
    },
    ...(rejected || withdrawn ? [] : [{
      label: 'Credit line active',
      detail: active
        ? `${money(account.available_credit)} available to spend`
        : approved ? 'Choose a purpose and activate to start using it' : null,
      done: active,
      current: approved && !active,
    }]),
  ];
}

function journeyStep(status) {
  if (status === 'KYC_PENDING') return 'KYC';
  if (status === 'APPROVED') return 'APPROVED';
  return 'REVIEW';
}

export default function CreditStatus() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: application, loading, error, refetch, setData } = useFetch(
    () => endpoints.credit.application(applicationId), [applicationId],
  );
  const { data: kyc } = useFetch(() => endpoints.kyc.status(), [application?.status]);
  const { data: account } = useFetch(
    () => endpoints.credit.account(), [application?.status],
    { skip: application?.status !== 'APPROVED' },
  );

  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);

  const isOpen = OPEN.includes(application?.status);

  useEffect(() => {
    if (!isOpen) return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await endpoints.credit.application(applicationId, { background: true });
        if (response.data.status !== application.status) {
          setData(response.data);
          if (response.data.status === 'APPROVED') toast.success('Approved! Your credit limit is ready.');
        }
      } catch {
        /* Keep the last known state on screen; the next tick tries again. */
      }
    }, POLL_EVERY_MS);
    return () => clearInterval(timer);
  }, [isOpen, applicationId, application?.status, setData, toast]);

  async function withdraw() {
    setWithdrawing(true);
    try {
      const response = await endpoints.credit.withdraw(applicationId);
      setData(response.data);
      toast.success('Application withdrawn.');
      setConfirmWithdraw(false);
    } catch (err) {
      toast.error(friendlyError(err, 'We could not withdraw this application.'));
    } finally {
      setWithdrawing(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Your application" back="/credit" />
        <Card className="space-y-4 p-6">
          <Skeleton className="mx-auto h-20 w-20 rounded-full" />
          <Skeleton className="h-40 w-full" />
        </Card>
      </div>
    );
  }

  if (!application) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Your application" back="/credit" />
        <ErrorCard
          error={error}
          title={error?.status === 404 ? 'Application not found' : 'We could not load your application'}
          onRetry={error?.status === 404 ? undefined : refetch}
        />
      </div>
    );
  }

  const status = application.status;
  const approved = status === 'APPROVED';
  const rejected = status === 'REJECTED';
  const withdrawn = status === 'WITHDRAWN';
  const needsKyc = status === 'KYC_PENDING';
  const kycState = kycDetail(kyc);
  const kycInReview = needsKyc && ['PENDING', 'UNDER_REVIEW'].includes(kyc?.kyc_status);

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Your application"
        subtitle={`Reference ${application.application_id.slice(0, 8).toUpperCase()}`}
        back="/credit"
        action={
          <Badge tone={approved ? 'good' : rejected || withdrawn ? 'alert' : 'warn'} dot>
            {status.replace(/_/g, ' ')}
          </Badge>
        }
      />

      {!withdrawn && (
        <JourneySteps current={journeyStep(status)} failed={rejected} className="mb-5" />
      )}

      {/* The headline outcome, before any detail. Somebody opening this screen
          wants one of three answers, and should not have to read to find it. */}
      <Card className="mb-4 p-6 sm:p-8">
        {approved && (
          <>
            <StatusHero
              kind="success"
              amount={money(application.approved_limit)}
              title="Approved"
              subtitle="Your credit limit is assigned. Choose what you will use it for, then activate your card."
            />
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-6"
              onClick={() => navigate(account?.status === 'ACTIVE' ? '/credit' : '/credit/purpose')}
            >
              {account?.status === 'ACTIVE' ? 'Go to my credit line' : 'Continue'}
            </Button>
          </>
        )}

        {needsKyc && (
          <>
            <StatusHero
              kind={kycState.tone === 'alert' ? 'failure' : 'pending'}
              title={
                kycInReview ? 'Your documents are being reviewed'
                  : kycState.tone === 'alert' ? 'KYC verification failed'
                    : 'Verify your identity'
              }
              subtitle={
                kycInReview
                  ? 'Your application is saved. Once your KYC is approved, it moves to review automatically.'
                  : kycState.tone === 'alert'
                    ? `${kycState.text}. Your application is saved - resubmit your documents to continue.`
                    : 'Your application is saved. Complete KYC and it moves to review - no need to apply again.'
              }
            />
            {!kycInReview && (
              <Button variant="mint" size="lg" full className="mt-6" onClick={() => navigate('/kyc')}>
                {kycState.tone === 'alert' ? 'Resubmit KYC' : 'Complete KYC'}
              </Button>
            )}
          </>
        )}

        {status === 'UNDER_REVIEW' && (
          <>
            <StatusHero
              kind="pending"
              title="Under review"
              subtitle="Nothing more is needed from you. This page updates by itself when there is a decision."
            />
            {/* The eligible limit, worked out from salary and credit score.
                Nothing here is chosen by the applicant. */}
            <div className="mt-5 grid grid-cols-2 gap-2 text-center">
              <div className="rounded-2xl border border-line bg-mist/40 p-3">
                <p className="text-2xs uppercase tracking-wider text-slate">Credit score</p>
                <p className="money mt-1 text-xl font-bold text-ink">
                  {application.credit_score
                    ?? (application.credit_status === 'PENDING' ? '—' : 'Not Available')}
                </p>
                <p className="text-2xs text-slate">
                  {application.credit_status === 'SCORED'
                    ? application.credit_score_band
                    : application.credit_status === 'PENDING' ? 'Being fetched' : application.credit_status_label}
                </p>
                {application.bureau_is_demo && <p className="text-2xs text-amber-700">Test data</p>}
              </div>
              <div className="rounded-2xl border border-mint-200 bg-mint-50/60 p-3">
                <p className="text-2xs uppercase tracking-wider text-slate">Eligible limit</p>
                <p className="money mt-1 text-xl font-bold text-ink">
                  {application.eligible_limit ? money(application.eligible_limit, { decimals: 0 }) : '—'}
                </p>
                <p className="text-2xs text-slate">Final once approved</p>
              </div>
            </div>
            {application.eligibility_checks?.length > 0 && (
              <ul className="mt-4 space-y-1.5 rounded-2xl border border-line p-3.5">
                {application.eligibility_checks.map((item) => (
                  <li key={item.key} className="flex items-start gap-2 text-xs">
                    <span className={cx('mt-0.5 font-bold', item.passed ? 'text-mint-700' : 'text-alert')}>
                      {item.passed ? '✓' : '✕'}
                    </span>
                    <span className="min-w-0">
                      <span className="font-medium text-ink">{item.label}</span>
                      <span className="text-slate"> - {item.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {application.assessment_message && (
              <p className="mt-3 rounded-xl bg-amber-50 px-3.5 py-3 text-center text-xs text-amber-800">
                {application.assessment_message}
              </p>
            )}
          </>
        )}

        {rejected && (
          <>
            <StatusHero
              kind="failure"
              title="Not approved"
              subtitle={application.decision_note || application.decision_message || 'We are unable to offer a credit line at this time.'}
            />
            <Button
              variant={application.decision_reason === 'FULL_KYC_REQUIRED' ? 'mint' : 'outline'}
              size="lg"
              full
              className="mt-6"
              onClick={() => navigate(application.decision_reason === 'FULL_KYC_REQUIRED' ? '/kyc' : '/credit/apply')}
            >
              {application.decision_reason === 'FULL_KYC_REQUIRED' ? 'Upgrade to full KYC' : 'Apply again'}
            </Button>
          </>
        )}

        {withdrawn && (
          <>
            <StatusHero
              kind="cancelled"
              title="Withdrawn"
              subtitle="You took this application back. You can start a new one whenever you like."
            />
            <Button variant="mint" size="lg" full className="mt-6" onClick={() => navigate('/credit/apply')}>
              Apply again
            </Button>
          </>
        )}
      </Card>

      <Card className="mb-4 p-5 sm:p-6">
        <p className="mb-4 text-2xs font-semibold uppercase tracking-wider text-slate">Progress</p>
        <Timeline steps={buildTimeline(application, kyc, account)} />
      </Card>

      <Card className="divide-y divide-line py-1">
        <p className="py-2.5 text-2xs font-semibold uppercase tracking-wider text-slate">What you told us</p>
        <Row label="Employment" value={application.employment_type.replace(/_/g, ' ').toLowerCase()} />
        {application.employer_name && <Row label="Employer" value={application.employer_name} />}
        {application.designation && <Row label="Designation" value={application.designation} />}
        {application.months_in_current_job != null && (
          <Row label="In this job" value={`${application.months_in_current_job} months`} />
        )}
        <Row label="Monthly income" value={money(application.monthly_income)} mono />
        <Row label="Existing EMIs" value={money(application.existing_emi_outflow || 0)} mono />
        {application.income_proof_label && (
          <Row label="Income proof" value={application.income_proof_label} />
        )}
        {application.bank_account && (
          <Row
            label="Salary account"
            value={`${application.bank_account.bank_name || 'Bank'} ${application.bank_account.masked_account}`}
          />
        )}
        <Row label="Submitted" value={date(application.submitted_at)} />
      </Card>

      {application.is_open && (
        <Button variant="ghost" size="lg" full className="mt-4" onClick={() => setConfirmWithdraw(true)}>
          Withdraw this application
        </Button>
      )}

      <Sheet
        open={confirmWithdraw}
        onClose={() => setConfirmWithdraw(false)}
        title="Withdraw your application?"
        footer={
          <div className="flex gap-2">
            <Button variant="outline" size="lg" full onClick={() => setConfirmWithdraw(false)}>
              Keep it
            </Button>
            <Button variant="danger" size="lg" full loading={withdrawing} onClick={withdraw}>
              Withdraw
            </Button>
          </div>
        }
      >
        <p className="text-sm leading-relaxed text-slate">
          We will stop reviewing it. You can apply again later, but you will start
          from the beginning.
        </p>
      </Sheet>
    </div>
  );
}
