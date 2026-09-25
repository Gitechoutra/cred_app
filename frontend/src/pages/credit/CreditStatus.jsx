import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Timeline } from '../../components/domain';
import { Badge, Button, Card, Row, Skeleton } from '../../components/ui';
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
 * The rejection path gets the same care as the approval path. A decline is the
 * outcome people most need explained, and the reason comes from the server as a
 * code with wording attached, so the same decision always reads the same way
 * rather than being phrased freshly here.
 */

const STAGES = ['KYC_PENDING', 'UNDER_REVIEW', 'APPROVED'];

function buildTimeline(application) {
  const status = application.status;
  const rejected = status === 'REJECTED';
  const withdrawn = status === 'WITHDRAWN';

  const steps = [{
    label: 'Application received',
    detail: application.submitted_at ? date(application.submitted_at) : null,
    done: true,
  }];

  steps.push({
    label: 'Identity verified',
    detail: application.kyc_verified_at
      ? date(application.kyc_verified_at)
      : 'Complete your KYC to continue',
    done: Boolean(application.kyc_verified_at),
    current: status === 'KYC_PENDING',
  });

  steps.push({
    label: 'Under review',
    detail: status === 'UNDER_REVIEW'
      ? 'Usually within one working day'
      : (application.decided_at ? date(application.decided_at) : null),
    done: STAGES.indexOf(status) > 1 || rejected,
    current: status === 'UNDER_REVIEW',
  });

  steps.push({
    label: rejected ? 'Not approved' : 'Decision',
    detail: rejected
      ? application.decision_message
      : (application.approved_limit
          ? `${money(application.approved_limit)} credit limit`
          : null),
    done: status === 'APPROVED' || rejected,
    current: status === 'APPROVED',
    failed: rejected || withdrawn,
  });

  return steps;
}

export default function CreditStatus() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: application, loading, refetch } = useFetch(
    () => endpoints.credit.application(applicationId), [applicationId],
  );

  async function withdraw() {
    try {
      await endpoints.credit.withdraw(applicationId);
      toast.success('Application withdrawn.');
      refetch();
    } catch (error) {
      toast.error(error?.message || 'We could not withdraw this application.');
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Your application" back />
        <Card><Skeleton className="h-64 w-full" /></Card>
      </div>
    );
  }

  if (!application) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Your application" back />
        <Card className="text-center">
          <p className="text-sm text-slate">We could not find that application.</p>
        </Card>
      </div>
    );
  }

  const approved = application.status === 'APPROVED';
  const rejected = application.status === 'REJECTED';
  const withdrawn = application.status === 'WITHDRAWN';
  const needsKyc = application.status === 'KYC_PENDING';

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Your application"
        subtitle={`Reference ${application.application_id.slice(0, 8).toUpperCase()}`}
        back
        action={
          <Badge tone={approved ? 'good' : rejected || withdrawn ? 'alert' : 'warn'} dot>
            {application.status.replace(/_/g, ' ')}
          </Badge>
        }
      />

      {/* The headline outcome, before any detail. Somebody opening this screen
          wants one of three answers, and should not have to read to find it. */}
      <Card className="mb-4 text-center">
        {approved && (
          <>
            <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
              Approved credit limit
            </p>
            <p className="money mt-1 text-4xl font-bold text-ink">
              {money(application.approved_limit)}
            </p>
            <p className="mt-2 text-sm text-slate">
              Choose what you will use it for, then activate your card.
            </p>
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-5"
              onClick={() => navigate('/credit/purpose')}
            >
              Continue
            </Button>
          </>
        )}

        {needsKyc && (
          <>
            <p className="text-base font-semibold text-ink">
              We need to verify your identity
            </p>
            <p className="mt-1 text-sm text-slate">
              Your application is saved. Complete KYC and we will decide it
              automatically - you do not need to apply again.
            </p>
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-5"
              onClick={() => navigate('/kyc')}
            >
              Verify my identity
            </Button>
          </>
        )}

        {application.status === 'UNDER_REVIEW' && (
          <>
            <p className="text-base font-semibold text-ink">Under review</p>
            <p className="mt-1 text-sm text-slate">
              Nothing more is needed from you. We will let you know as soon as
              there is a decision.
            </p>
            {application.offered_limit > 0 && (
              <p className="mt-3 text-xs text-slate">
                Indicative limit{' '}
                <span className="money font-medium text-ink">
                  {money(application.offered_limit)}
                </span>
                {' '}- not final until the decision is made.
              </p>
            )}
          </>
        )}

        {rejected && (
          <>
            <p className="text-base font-semibold text-ink">Not approved</p>
            <p className="mt-2 text-sm text-slate">
              {application.decision_message
                || 'We are unable to offer a credit line at this time.'}
            </p>
            {application.decision_reason === 'FULL_KYC_REQUIRED' && (
              <Button
                variant="mint"
                size="lg"
                full
                className="mt-5"
                onClick={() => navigate('/kyc')}
              >
                Upgrade to full KYC
              </Button>
            )}
            {application.decision_reason !== 'FULL_KYC_REQUIRED' && (
              <Button
                variant="outline"
                size="lg"
                full
                className="mt-5"
                onClick={() => navigate('/credit/apply')}
              >
                Apply again
              </Button>
            )}
          </>
        )}

        {withdrawn && (
          <>
            <p className="text-base font-semibold text-ink">Withdrawn</p>
            <p className="mt-1 text-sm text-slate">
              You took this application back. You can start a new one whenever
              you like.
            </p>
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-5"
              onClick={() => navigate('/credit/apply')}
            >
              Apply again
            </Button>
          </>
        )}
      </Card>

      <Card className="mb-4">
        <p className="mb-4 text-2xs font-semibold uppercase tracking-wider text-slate">
          Progress
        </p>
        <Timeline steps={buildTimeline(application)} />
      </Card>

      <Card>
        <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate">
          What you told us
        </p>
        <Row
          label="Employment"
          value={application.employment_type.replace(/_/g, ' ').toLowerCase()}
        />
        <Row label="Monthly income" value={money(application.monthly_income)} mono />
        {application.existing_emi_outflow > 0 && (
          <Row
            label="Existing EMIs"
            value={money(application.existing_emi_outflow)}
            mono
          />
        )}
        {application.requested_limit > 0 && (
          <Row
            label="Limit you asked for"
            value={money(application.requested_limit)}
            mono
          />
        )}
        <Row label="Submitted" value={date(application.submitted_at)} />
      </Card>

      {application.is_open && (
        <Button
          variant="ghost"
          size="lg"
          full
          className="mt-4"
          onClick={withdraw}
        >
          Withdraw this application
        </Button>
      )}
    </div>
  );
}
