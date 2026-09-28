import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Input, Skeleton, cx } from '../../components/ui';
import {
  ErrorCard, JourneySteps, ProcessingPanel, friendlyError,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { useSessionDraft } from '../../hooks/useSessionDraft';
import { money, sanitizeAmount } from '../../utils/format';

/**
 * Apply for a credit card.
 *
 * There is no limit to ask for. The applicant gives their salary and existing
 * EMIs and consents to a credit score check; the eligible limit is worked out
 * from those on the server and shown on the status screen. Asking for a limit
 * used to be possible, and it was a way for the number to drift from the
 * evidence - so the field, and the estimate that went with it, are gone.
 *
 * KYC is not a precondition for applying. An unverified applicant submits and is
 * told to verify next - being turned away at the door and asked to come back
 * after a day of document review is a worse journey than being told the
 * application is in and what remains.
 *
 * What is typed survives leaving the screen, so checking something elsewhere
 * and coming back does not mean starting again.
 */

const EMPLOYMENT = [
  { value: 'SALARIED', label: 'Salaried', hint: 'Regular monthly income' },
  { value: 'SELF_EMPLOYED', label: 'Self-employed', hint: 'Business or freelance' },
  { value: 'STUDENT', label: 'Student', hint: 'Limits are lower' },
  { value: 'RETIRED', label: 'Retired', hint: 'Pension or investments' },
  { value: 'OTHER', label: 'Other', hint: 'Limits are lower' },
];

//: The server refuses a declared income above this as a typo or a probe.
const INCOME_CEILING = 100000000;

//: How the limit is worked out, mirroring credit_engine.SCORE_BANDS. Shown so
//: the process is not a black box; the server is what applies it.
const BANDS = [
  { range: '800+', label: 'Excellent', months: 4 },
  { range: '750-799', label: 'Very good', months: 3 },
  { range: '700-749', label: 'Good', months: 2 },
  { range: '650-699', label: 'Fair', months: 1 },
];

const EMPTY = { employment: 'SALARIED', income: '', outflow: '', consent: false };

export default function CreditApply() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: eligibility, loading, error: loadError, refetch } = useFetch(
    () => endpoints.credit.eligibility(), [],
  );

  const [form, update, clearDraft] = useSessionDraft('credit-apply', EMPTY);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [busy, setBusy] = useState(false);


  function set(patch) {
    update(patch);
    setErrors((current) => {
      const next = { ...current };
      Object.keys(patch).forEach((key) => delete next[key]);
      return next;
    });
    setSubmitError(null);
  }

  function validate() {
    const found = {};
    const monthly = Number(form.income);
    const emis = Number(form.outflow || 0);

    if (!form.income) found.income = 'Enter your monthly income.';
    else if (!Number.isFinite(monthly) || monthly <= 0) found.income = 'Enter a valid monthly income.';
    else if (monthly > INCOME_CEILING) found.income = 'That looks too high. Enter your monthly take-home pay.';

    if (form.outflow && (!Number.isFinite(emis) || emis < 0)) {
      found.outflow = 'Enter a valid amount, or leave this blank.';
    } else if (monthly > 0 && emis >= monthly) {
      found.outflow = 'Your existing EMIs must be less than your income.';
    }

    if (!form.consent) {
      found.consent = 'We need your permission to check your credit score.';
    }

    setErrors(found);
    return Object.keys(found).length === 0;
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || !validate()) return;

    setBusy(true);
    setSubmitError(null);
    try {
      const response = await endpoints.credit.apply({
        employment_type: form.employment,
        monthly_income: form.income,
        existing_emi_outflow: form.outflow || undefined,
        bureau_consent: form.consent,
      });
      clearDraft();
      toast.success(response.message || 'Application submitted.');
      // Replaced, so back from the status page goes to where the applicant
      // started rather than to a form that has already been submitted.
      navigate(`/credit/status/${response.data.application_id}`, { replace: true });
    } catch (err) {
      // A 409 means they already have an application or a card. Sending them to
      // the thing that already exists beats an error they cannot act on.
      if (err?.code === 'CONFLICT') {
        toast.info(err.message);
        clearDraft();
        navigate('/credit', { replace: true });
        return;
      }
      setSubmitError(err);
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Apply for a credit card" back="/credit" />
        <Card className="space-y-4 p-6">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </Card>
      </div>
    );
  }

  if (!eligibility) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Apply for a credit card" back="/credit" />
        <ErrorCard error={loadError} title="We could not check your eligibility" onRetry={refetch} />
      </div>
    );
  }

  if (!eligibility.can_apply) {
    return (
      <div className="mx-auto w-full max-w-2xl animate-fade-up">
        <PageHeader title="Apply for a credit card" back="/credit" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">
            {eligibility.has_credit_line
              ? 'You already have a credit card'
              : 'You already have an application in progress'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {eligibility.has_credit_line
              ? 'One card at a time.'
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

  if (busy) {
    return (
      <ProcessingPanel
        title="Submitting your application"
        subtitle="Checking your details against our eligibility rules. This takes a moment."
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        eyebrow="Step 1 of 6"
        title="Apply for a credit card"
        subtitle="Two minutes. Nothing is opened until you accept."
        back="/credit"
      />

      <JourneySteps current="APPLY" className="mb-5" />

      {eligibility.kyc_required && (
        <Card className="mb-4 border-amber-200 bg-amber-50/50">
          <div className="flex items-start gap-3">
            <Badge tone="warn" dot>KYC</Badge>
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">You can apply now and verify after</p>
              <p className="mt-0.5 text-xs text-slate">
                We will hold your application while you complete KYC, then decide
                it. Your card cannot be used until verification is complete.
              </p>
            </div>
          </div>
        </Card>
      )}

      <form onSubmit={submit} noValidate>
        <Card className="space-y-6 p-5 sm:p-6">
          <fieldset>
            <legend className="text-sm font-semibold text-ink">What do you do?</legend>
            <p className="mt-0.5 text-xs text-slate">This affects the limit we can offer.</p>

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {EMPLOYMENT.map((option) => {
                const active = form.employment === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => set({ employment: option.value })}
                    aria-pressed={active}
                    className={cx(
                      'rounded-2xl border p-3.5 text-left transition-all duration-base active:scale-[0.99]',
                      active ? 'border-mint bg-mint-50 ring-2 ring-mint/25' : 'border-line bg-canvas hover:border-ink/20',
                    )}
                  >
                    <span className="block text-sm font-medium text-ink">{option.label}</span>
                    <span className="mt-0.5 block text-2xs text-slate">{option.hint}</span>
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
            value={form.income}
            onChange={(event) => set({ income: sanitizeAmount(event.target.value) })}
            error={errors.income}
            hint="Take-home, after tax."
            required
          />

          <Input
            label="Existing EMIs each month"
            prefix="₹"
            inputMode="decimal"
            placeholder="0"
            value={form.outflow}
            onChange={(event) => set({ outflow: sanitizeAmount(event.target.value) })}
            error={errors.outflow}
            hint="Loan and card repayments you already make. Leave blank if none."
          />

          {/* How the limit is decided. There is nothing to choose here - it is
              explained so the applicant knows what the number will rest on. */}
          <div className="rounded-2xl border border-line bg-gradient-to-br from-mint-50/70 to-canvas p-4">
            <p className="text-sm font-semibold text-ink">How your limit is decided</p>
            <p className="mt-1 text-xs leading-relaxed text-slate">
              From your salary, less the EMIs you already pay, and your CIBIL
              credit score. You do not need to choose a limit - we work out the
              highest one you are eligible for.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {BANDS.map((band) => (
                <div key={band.range} className="rounded-xl border border-line bg-canvas px-2.5 py-2">
                  <p className="money text-xs font-bold text-ink">{band.range}</p>
                  <p className="text-2xs text-slate">{band.label}</p>
                  <p className="mt-1 text-2xs font-medium text-mint-800">
                    {band.months}x monthly surplus
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-2xs text-slate">
              Scores below 650 are not eligible yet. With minimum KYC, limits
              are up to {money(eligibility.full_kyc_required_above, { decimals: 0 })};
              full KYC unlocks more.
            </p>
          </div>

          <label
            className={cx(
              'flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 transition',
              errors.consent ? 'border-alert ring-2 ring-alert/15' : 'border-line hover:border-ink/20',
            )}
          >
            <input
              type="checkbox"
              checked={form.consent}
              onChange={(event) => set({ consent: event.target.checked })}
              className="mt-0.5 h-4 w-4 shrink-0 accent-mint-600"
            />
            <span className="text-xs leading-relaxed text-slate">
              <span className="font-medium text-ink">
                I authorise CashU to fetch my credit report from a credit bureau
              </span>{' '}
              using my PAN, to decide my credit limit. This is a soft enquiry and
              does not affect my credit score.
            </span>
          </label>
          {errors.consent && <p className="-mt-3 text-xs text-alert">{errors.consent}</p>}

          {submitError && (
            <p className="rounded-xl bg-red-50 px-3.5 py-3 text-sm text-alert" role="alert">
              {friendlyError(submitError, 'We could not submit your application. Please try again.')}
            </p>
          )}

          <Button type="submit" variant="mint" size="lg" full>
            Submit application
          </Button>

          <p className="text-center text-2xs text-slate">
            Submitting does not open a card. Once approved you choose what the credit
            is for, then activate it.
          </p>
        </Card>
      </form>
    </div>
  );
}
