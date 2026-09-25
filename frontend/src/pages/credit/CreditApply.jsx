import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { money, sanitizeAmount } from '../../utils/format';

/**
 * Apply for a credit line.
 *
 * The number shown while typing is an *estimate*, computed here purely so the
 * form is not a black box. It is labelled as an estimate everywhere it appears,
 * and it is never sent: the limit that gets granted is computed by the backend
 * from the same declared figures, and this screen has no way to influence it.
 * Two numbers that disagree would be worse than one number that is honest about
 * being provisional, so the copy says so rather than implying a promise.
 *
 * KYC is not a precondition for applying. An unverified applicant submits and is
 * told to verify next - being turned away at the door and asked to come back
 * after a day of document review is a worse journey than being told the
 * application is in and what remains.
 */

const EMPLOYMENT = [
  { value: 'SALARIED', label: 'Salaried', hint: 'Regular monthly income' },
  { value: 'SELF_EMPLOYED', label: 'Self-employed', hint: 'Business or freelance' },
  { value: 'STUDENT', label: 'Student', hint: 'Limits are lower' },
  { value: 'RETIRED', label: 'Retired', hint: 'Pension or investments' },
  { value: 'OTHER', label: 'Other', hint: 'Limits are lower' },
];

//: Mirrors credit_engine.DISPOSABLE_INCOME_MULTIPLE and THIN_FILE_CAP. Kept in
//: step deliberately: if these drift, the estimate stops matching the offer and
//: the screen starts lying. The backend remains authoritative either way.
const DISPOSABLE_MULTIPLE = 3;
const THIN_FILE_CAP = 20000;
const THIN_FILE = ['STUDENT', 'OTHER'];

function estimate({ employment, income, outflow, requested, tierCap }) {
  const disposable = Number(income || 0) - Number(outflow || 0);
  if (disposable <= 0) return 0;

  let offer = disposable * DISPOSABLE_MULTIPLE;
  if (THIN_FILE.includes(employment)) offer = Math.min(offer, THIN_FILE_CAP);
  if (requested) offer = Math.min(offer, Number(requested));
  if (tierCap) offer = Math.min(offer, Number(tierCap));

  return Math.floor(offer / 500) * 500;
}

export default function CreditApply() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: eligibility, loading } = useFetch(
    () => endpoints.credit.eligibility(), [],
  );

  const [employment, setEmployment] = useState('SALARIED');
  const [income, setIncome] = useState('');
  const [outflow, setOutflow] = useState('');
  const [requested, setRequested] = useState('');
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  const tierCap = eligibility?.max_limit_for_tier;
  const floor = eligibility?.minimum_limit ?? 5000;

  const provisional = estimate({
    employment, income, outflow, requested, tierCap,
  });

  function validate() {
    const found = {};
    const monthly = Number(income);

    if (!income) found.income = 'Enter your monthly income.';
    else if (!Number.isFinite(monthly) || monthly <= 0) {
      found.income = 'Enter a valid monthly income.';
    }

    if (outflow && Number(outflow) >= monthly) {
      found.outflow = 'Your existing EMIs cannot exceed your income.';
    }

    if (requested && Number(requested) <= 0) {
      found.requested = 'Enter a valid amount, or leave this blank.';
    }

    setErrors(found);
    return Object.keys(found).length === 0;
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || !validate()) return;

    setBusy(true);
    try {
      const response = await endpoints.credit.apply({
        employment_type: employment,
        monthly_income: income,
        existing_emi_outflow: outflow || 0,
        requested_limit: requested || undefined,
      });
      toast.success(response.message || 'Application submitted.');
      navigate(`/credit/status/${response.data.application_id}`, { replace: true });
    } catch (error) {
      // A 409 means they already have an application or a card. Sending them to
      // the thing that already exists beats an error they cannot act on.
      if (error?.code === 'CONFLICT') {
        toast.info(error.message);
        navigate('/credit', { replace: true });
        return;
      }
      toast.error(error?.message || 'We could not submit your application.');
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Apply for credit" back />
        <Card><Skeleton className="h-64 w-full" /></Card>
      </div>
    );
  }

  if (eligibility && !eligibility.can_apply) {
    return (
      <div className="mx-auto w-full max-w-2xl animate-fade-up">
        <PageHeader title="Apply for credit" back />
        <Card className="text-center">
          <p className="text-base font-semibold text-ink">
            {eligibility.has_credit_line
              ? 'You already have a credit line'
              : 'You already have an application in progress'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {eligibility.has_credit_line
              ? 'One credit line at a time. Close it before applying for another.'
              : 'We will let you know as soon as it is decided.'}
          </p>
          <Button
            variant="mint"
            size="lg"
            className="mt-5"
            onClick={() => navigate(
              eligibility.has_credit_line
                ? '/credit'
                : `/credit/status/${eligibility.open_application_id}`,
              { replace: true },
            )}
          >
            {eligibility.has_credit_line ? 'View my card' : 'Check the status'}
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Apply for credit"
        subtitle="Two minutes. No impact on anything until you accept an offer."
        back
      />

      {eligibility?.kyc_required && (
        <Card className="mb-4 border-mint-600/30 bg-mint-50/40">
          <div className="flex items-start gap-3">
            <Badge tone="warn" dot>KYC</Badge>
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">
                You can apply now, verify after
              </p>
              <p className="mt-0.5 text-xs text-slate">
                We will hold your application while you complete KYC, then decide
                it automatically. Nothing is lost by starting here.
              </p>
            </div>
          </div>
        </Card>
      )}

      <form onSubmit={submit} noValidate>
        <Card className="space-y-6">
          <fieldset>
            <legend className="text-sm font-semibold text-ink">
              What do you do?
            </legend>
            <p className="mt-0.5 text-xs text-slate">
              This affects the limit we can offer.
            </p>

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {EMPLOYMENT.map((option) => {
                const active = employment === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setEmployment(option.value)}
                    aria-pressed={active}
                    className={cx(
                      'rounded-xl border p-3 text-left transition active:scale-[0.99]',
                      active
                        ? 'border-mint bg-mint-50 shadow-mint'
                        : 'border-line bg-canvas hover:border-ink/20',
                    )}
                  >
                    <span className="block text-sm font-medium text-ink">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-2xs text-slate">
                      {option.hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <Input
            label="Monthly income"
            prefix="₹"
            inputMode="decimal"
            placeholder="60,000"
            value={income}
            onChange={(event) => setIncome(sanitizeAmount(event.target.value))}
            error={errors.income}
            hint="Take-home, after tax."
            required
          />

          <Input
            label="Existing EMIs each month"
            prefix="₹"
            inputMode="decimal"
            placeholder="0"
            value={outflow}
            onChange={(event) => setOutflow(sanitizeAmount(event.target.value))}
            error={errors.outflow}
            hint="Loan and card repayments you already make. Leave blank if none."
          />

          <Input
            label="Limit you want (optional)"
            prefix="₹"
            inputMode="decimal"
            placeholder="Leave blank for the maximum you qualify for"
            value={requested}
            onChange={(event) => setRequested(sanitizeAmount(event.target.value))}
            error={errors.requested}
            hint="Asking for less than you qualify for is honoured. Asking for more is not."
          />

          {provisional > 0 && (
            <div className="rounded-2xl border border-line bg-mist/60 p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm text-slate">Estimated limit</span>
                <span className="money text-xl font-bold text-ink">
                  {money(provisional)}
                </span>
              </div>
              <p className="mt-2 border-t border-line pt-2 text-2xs leading-relaxed text-slate">
                An estimate from what you have entered, not an offer. The limit is
                decided by our systems when the application is reviewed, and can
                differ from this.
                {provisional < floor && (
                  <> This is below our minimum of {money(floor)}, so it would not
                  be approved as it stands.</>
                )}
              </p>
            </div>
          )}

          {tierCap && (
            <Row
              label={`Maximum for your ${eligibility.kyc_tier} KYC`}
              value={money(tierCap)}
              mono
            />
          )}

          <Button type="submit" variant="mint" size="lg" full loading={busy}>
            Submit application
          </Button>

          <p className="text-center text-2xs text-slate">
            Submitting does not open a credit line. You choose what the credit is
            for, and activate it, after a decision.
          </p>
        </Card>
      </form>
    </div>
  );
}
