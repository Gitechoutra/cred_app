import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import {
  ErrorCard, JourneySteps, ProcessingPanel, friendlyError,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { useSessionDraft } from '../../hooks/useSessionDraft';
import { money, sanitizeAmount } from '../../utils/format';

/**
 * The credit application.
 *
 * Four steps, the way a lender takes one: who you are (KYC - PAN and Aadhaar),
 * the bank account your salary lands in (penny-drop verified), what you do and
 * earn (with a document that shows it), and permission to check your credit
 * score. Then it goes to review.
 *
 * There is no limit on this screen - not an input, not an estimate. The
 * eligible limit is worked out on the server from the verified income and the
 * credit bureau score, and an administrator approves or rejects it. The
 * applicant finds out the number on the status screen, from the server, once
 * it exists; a number computed here could only ever disagree with it.
 *
 * What is typed survives leaving the screen - to link a bank account, say - so
 * coming back does not mean starting again. Files cannot be kept that way, so
 * the income proof is asked for on the step after the bank, and never has to
 * be picked twice.
 */

const STEPS = [
  { key: 'identity', label: 'Identity' },
  { key: 'bank', label: 'Bank' },
  { key: 'income', label: 'Employment & income' },
  { key: 'consent', label: 'Credit check' },
];

const EMPLOYMENT = [
  { value: 'SALARIED', label: 'Salaried', hint: 'Regular monthly salary' },
  { value: 'SELF_EMPLOYED', label: 'Self-employed', hint: 'Business or professional' },
  { value: 'RETIRED', label: 'Retired', hint: 'Pension or investments' },
  { value: 'STUDENT', label: 'Student', hint: 'Stipend or allowance' },
  { value: 'OTHER', label: 'Other', hint: 'Any other income' },
];

//: The server refuses a declared income above this as a typo or a probe.
const INCOME_CEILING = 100000000;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

const EMPTY = {
  step: 0,
  employment: 'SALARIED',
  employer: '',
  designation: '',
  months: '',
  income: '',
  outflow: '',
  proofType: 'SALARY_SLIP',
  bankId: '',
  consent: false,
};

function fileProblem(file) {
  if (!file) return null;
  if (!/\.(pdf|jpe?g|png)$/i.test(file.name)) return 'Upload a PDF, JPG or PNG.';
  if (file.size > MAX_FILE_BYTES) return 'That file is over 5 MB.';
  return null;
}

export default function CreditApply() {
  const navigate = useNavigate();
  const toast = useToast();
  const { refresh } = useProfile();

  const { data: eligibility, loading, error: loadError, refetch } = useFetch(
    () => endpoints.credit.eligibility(), [],
  );

  const [form, update, clearDraft] = useSessionDraft('credit-application', EMPTY);
  const [proof, setProof] = useState(null);
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

  const step = Math.min(form.step || 0, STEPS.length - 1);
  const goTo = (index) => {
    set({ step: index });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Apply for a credit line" back="/credit" />
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
        <PageHeader title="Apply for a credit line" back="/credit" />
        <ErrorCard error={loadError} title="We could not load your application" onRetry={refetch} />
      </div>
    );
  }

  if (!eligibility.can_apply) {
    return (
      <div className="mx-auto w-full max-w-2xl animate-fade-up">
        <PageHeader title="Apply for a credit line" back="/credit" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">
            {eligibility.has_credit_line
              ? 'You already have a credit line'
              : 'You already have an application in progress'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {eligibility.has_credit_line
              ? 'One credit line at a time.'
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
            {eligibility.has_credit_line ? 'View my credit line' : 'Check the status'}
          </Button>
        </Card>
      </div>
    );
  }

  const kycDone = eligibility.kyc_submitted;
  const accounts = eligibility.bank_accounts || [];
  const verifiedAccounts = accounts.filter((a) => a.is_verified);
  const bankId = verifiedAccounts.some((a) => a.bank_account_id === form.bankId)
    ? form.bankId
    : (verifiedAccounts[0]?.bank_account_id || '');
  const bank = accounts.find((a) => a.bank_account_id === bankId);
  const needsEmployer = (eligibility.employment_requires_employer || ['SALARIED', 'SELF_EMPLOYED'])
    .includes(form.employment);
  const proofTypes = eligibility.income_proof_types || [];

  function validateIncome() {
    const found = {};
    const monthly = Number(form.income);
    const emis = Number(form.outflow || 0);

    if (needsEmployer && !form.employer.trim()) {
      found.employer = form.employment === 'SELF_EMPLOYED'
        ? 'Enter your business name.'
        : 'Enter your employer.';
    }
    if (form.months && !/^\d{1,3}$/.test(String(form.months))) {
      found.months = 'Enter a number of months.';
    }
    if (!form.income) found.income = 'Enter your monthly income.';
    else if (!Number.isFinite(monthly) || monthly <= 0) found.income = 'Enter a valid monthly income.';
    else if (monthly > INCOME_CEILING) found.income = 'That looks too high. Enter your monthly take-home pay.';

    if (form.outflow && (!Number.isFinite(emis) || emis < 0)) {
      found.outflow = 'Enter a valid amount, or leave this blank.';
    } else if (monthly > 0 && emis >= monthly) {
      found.outflow = 'Your existing EMIs must be less than your income.';
    }

    if (!proof) found.proof = 'Upload your proof of income.';
    else if (fileProblem(proof)) found.proof = fileProblem(proof);

    setErrors(found);
    return Object.keys(found).length === 0;
  }

  async function submit() {
    if (busy) return;
    if (!form.consent) {
      setErrors({ consent: 'We need your permission to check your credit score.' });
      return;
    }
    if (!validateIncome()) {
      goTo(2);
      return;
    }

    setBusy(true);
    setSubmitError(null);
    try {
      const body = new FormData();
      body.append('employment_type', form.employment);
      if (needsEmployer || form.employer.trim()) body.append('employer_name', form.employer.trim());
      if (form.designation.trim()) body.append('designation', form.designation.trim());
      if (form.months) body.append('months_in_current_job', String(form.months));
      body.append('monthly_income', form.income);
      body.append('existing_emi_outflow', form.outflow || '0');
      body.append('income_proof_type', form.proofType);
      body.append('income_proof', proof);
      body.append('bank_account_id', bankId);
      body.append('bureau_consent', 'true');

      const response = await endpoints.credit.apply(body);
      clearDraft();
      toast.success(response.message || 'Application submitted.');
      // Replaced, so back from the status page goes to where the applicant
      // started rather than to a form that has already been submitted.
      navigate(`/credit/status/${response.data.application_id}`, { replace: true });
    } catch (err) {
      // A 409 means they already have an application or a credit line. Sending
      // them to the thing that already exists beats an error they cannot act on.
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

  if (busy) {
    return (
      <ProcessingPanel
        title="Submitting your application"
        subtitle="Verifying your details and checking your credit score. This takes a moment."
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        eyebrow={`Step ${step + 1} of ${STEPS.length}`}
        title="Apply for a credit line"
        subtitle="Your limit is worked out from your income and credit score."
        back="/credit"
      />

      <JourneySteps current="APPLY" className="mb-4" />
      <StepBar steps={STEPS} current={step} onPick={(index) => index < step && goTo(index)} />

      {step === 0 && (
        <IdentityStep
          eligibility={eligibility}
          onSubmitted={async () => {
            await Promise.all([refetch(), refresh()]);
          }}
          onNext={() => goTo(1)}
          ready={kycDone}
        />
      )}

      {step === 1 && (
        <Card className="space-y-4 p-5 sm:p-6">
          <div>
            <h2 className="text-base font-semibold text-ink">Salary bank account</h2>
            <p className="mt-0.5 text-xs text-slate">
              The account your income is paid into. It must be in your name - we
              verify it by depositing ₹1 and matching the name the bank holds.
            </p>
          </div>

          {accounts.length === 0 && (
            <div className="rounded-2xl border border-dashed border-line bg-mist/40 p-5 text-center">
              <p className="text-sm font-medium text-ink">No bank account linked yet</p>
              <p className="mt-0.5 text-xs text-slate">Link one to continue. It takes a minute.</p>
            </div>
          )}

          <div className="space-y-2" role="radiogroup" aria-label="Bank account">
            {accounts.map((account) => {
              const active = account.bank_account_id === bankId;
              return (
                <button
                  key={account.bank_account_id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={!account.is_verified}
                  onClick={() => set({ bankId: account.bank_account_id })}
                  className={cx(
                    'flex w-full items-center justify-between gap-3 rounded-2xl border p-3.5 text-left transition-all duration-base',
                    active ? 'border-mint bg-mint-50 ring-2 ring-mint/25' : 'border-line bg-canvas hover:border-ink/20',
                    !account.is_verified && 'cursor-not-allowed opacity-60 hover:border-line',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink">
                      {account.bank_name || 'Bank account'}
                    </span>
                    <span className="money mt-0.5 block text-2xs text-slate">
                      {account.masked_account} · {account.ifsc_code}
                    </span>
                  </span>
                  <Badge tone={account.is_verified ? 'good' : 'warn'} dot>
                    {account.is_verified ? 'Verified' : account.penny_drop_status.replace(/_/g, ' ').toLowerCase()}
                  </Badge>
                </button>
              );
            })}
          </div>

          <Button
            variant="outline"
            size="lg"
            full
            onClick={() => navigate('/banks/add', { state: { returnTo: '/credit/apply' } })}
          >
            Link a bank account
          </Button>

          <StepFooter
            onBack={() => goTo(0)}
            onNext={() => goTo(2)}
            nextDisabled={!bankId}
            hint={!bankId ? 'Link and verify a bank account to continue.' : null}
          />
        </Card>
      )}

      {step === 2 && (
        <Card className="space-y-6 p-5 sm:p-6">
          <fieldset>
            <legend className="text-base font-semibold text-ink">Employment</legend>
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

          {needsEmployer && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Input
                  label={form.employment === 'SELF_EMPLOYED' ? 'Business name' : 'Employer'}
                  placeholder={form.employment === 'SELF_EMPLOYED' ? 'Sharma Traders' : 'Acme Technologies Pvt Ltd'}
                  value={form.employer}
                  maxLength={150}
                  onChange={(event) => set({ employer: event.target.value })}
                  error={errors.employer}
                  required
                />
              </div>
              <Input
                label={form.employment === 'SELF_EMPLOYED' ? 'Nature of business' : 'Designation'}
                placeholder={form.employment === 'SELF_EMPLOYED' ? 'Retail' : 'Software engineer'}
                value={form.designation}
                maxLength={100}
                onChange={(event) => set({ designation: event.target.value })}
              />
              <Input
                label="Months in this job"
                inputMode="numeric"
                placeholder="24"
                value={form.months}
                onChange={(event) => set({ months: event.target.value.replace(/\D/g, '').slice(0, 3) })}
                error={errors.months}
              />
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
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
              hint="Loans and cards you already repay."
            />
          </div>

          <fieldset>
            <legend className="text-sm font-semibold text-ink">Proof of income</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {proofTypes.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={form.proofType === option.value}
                  onClick={() => set({ proofType: option.value })}
                  className={cx(
                    'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                    form.proofType === option.value
                      ? 'border-ink bg-ink text-white'
                      : 'border-line bg-canvas text-slate hover:border-ink/20',
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <FileField
              className="mt-3"
              file={proof}
              error={errors.proof}
              onPick={(file) => {
                setProof(file);
                setErrors((current) => ({ ...current, proof: fileProblem(file) || undefined }));
              }}
              prompt="Upload document"
            />
          </fieldset>

          <StepFooter
            onBack={() => goTo(1)}
            onNext={() => { if (validateIncome()) goTo(3); }}
          />
        </Card>
      )}

      {step === 3 && (
        <Card className="space-y-5 p-5 sm:p-6">
          <div>
            <h2 className="text-base font-semibold text-ink">Review and submit</h2>
            <p className="mt-0.5 text-xs text-slate">Check your details, then allow the credit check.</p>
          </div>

          <div className="divide-y divide-line rounded-2xl border border-line px-4">
            <Row
              label="Identity"
              value={eligibility.kyc_tier !== 'NONE'
                ? `${eligibility.kyc_tier} KYC verified`
                : 'KYC submitted, in review'}
            />
            <Row label="Bank account" value={bank ? `${bank.bank_name || 'Bank'} ${bank.masked_account}` : '—'} />
            <Row label="Employment" value={EMPLOYMENT.find((e) => e.value === form.employment)?.label} />
            {needsEmployer && <Row label={form.employment === 'SELF_EMPLOYED' ? 'Business' : 'Employer'} value={form.employer} />}
            <Row label="Monthly income" value={money(form.income || 0)} mono />
            <Row label="Existing EMIs" value={money(form.outflow || 0)} mono />
            <Row
              label="Income proof"
              value={proof ? proofTypes.find((p) => p.value === form.proofType)?.label : 'Missing'}
              tone={proof ? undefined : 'alert'}
            />
          </div>

          <div className="rounded-2xl border border-line bg-mist/40 p-4">
            <p className="text-sm font-semibold text-ink">How your limit is decided</p>
            <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-slate">
              <li>· Your income, less the EMIs you already pay, sets what you can afford.</li>
              <li>· Your credit score decides how many months of that we can extend - more for a stronger score.</li>
              <li>· Your KYC level sets the maximum. A reviewer then approves or declines the result.</li>
            </ul>
          </div>

          <label
            className={cx(
              'flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition-colors',
              form.consent ? 'border-mint bg-mint-50/60' : 'border-line',
              errors.consent && 'border-alert',
            )}
          >
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-[#00F5B8]"
              checked={form.consent}
              onChange={(event) => set({ consent: event.target.checked })}
            />
            <span className="text-xs leading-relaxed text-slate">
              <span className="block text-sm font-medium text-ink">Check my credit score</span>
              I authorise CashU to fetch my credit report from a credit bureau
              (CIBIL, Experian, Equifax or CRIF) using my PAN, to assess this
              application. This is a soft enquiry and does not affect my score.
            </span>
          </label>
          {errors.consent && <p className="-mt-3 text-xs text-alert">{errors.consent}</p>}

          {submitError && (
            <p className="rounded-xl bg-red-50 px-3.5 py-3 text-sm text-alert" role="alert">
              {friendlyError(submitError, 'We could not submit your application. Please try again.')}
            </p>
          )}

          <div className="flex gap-2">
            <Button variant="outline" size="lg" onClick={() => goTo(2)}>Back</Button>
            <Button variant="mint" size="lg" full onClick={submit} disabled={!form.consent || !proof}>
              Submit application
            </Button>
          </div>

          <p className="text-center text-2xs text-slate">
            Submitting does not open a credit line. After approval you choose what
            it is for, and activate it.
          </p>
        </Card>
      )}
    </div>
  );
}

/* ── Identity (KYC) ─────────────────────────────────────────────────────── */

/**
 * KYC as a step of the application. Already verified, or submitted and in
 * review: shown, and the applicant moves on. Not started or rejected: PAN and
 * Aadhaar are taken here, so the application is one journey rather than a
 * detour to another screen.
 */
function IdentityStep({ eligibility, onSubmitted, onNext, ready }) {
  const toast = useToast();
  const status = eligibility.kyc_status;
  const verified = eligibility.kyc_tier !== 'NONE';
  const inReview = ['PENDING', 'UNDER_REVIEW'].includes(status);

  const [name, setName] = useState(eligibility.kyc_legal_name || '');
  const [pan, setPan] = useState('');
  const [aadhaar, setAadhaar] = useState('');
  const [files, setFiles] = useState({});
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  async function submitKyc() {
    const found = {};
    if (name.trim().length < 2) found.name = 'Enter your full name as on your PAN.';
    if (!PAN_PATTERN.test(pan)) found.pan = 'Enter a valid PAN, like ABCDE1234F.';
    if (!/^\d{12}$/.test(aadhaar)) found.aadhaar = 'Enter your 12-digit Aadhaar number.';
    if (!files.pan) found.panDoc = 'Upload your PAN card.';
    else if (fileProblem(files.pan)) found.panDoc = fileProblem(files.pan);
    if (!files.aadhaar) found.aadhaarDoc = 'Upload your Aadhaar card.';
    else if (fileProblem(files.aadhaar)) found.aadhaarDoc = fileProblem(files.aadhaar);
    setErrors(found);
    if (Object.keys(found).length) return;

    setBusy(true);
    try {
      const body = new FormData();
      body.append('full_name', name.trim());
      body.append('pan_number', pan);
      body.append('aadhaar_number', aadhaar);
      body.append('requested_tier', 'FULL');
      body.append('pan_document', files.pan);
      body.append('aadhaar_document', files.aadhaar);
      await endpoints.kyc.submit(body);
      toast.success('KYC submitted. You can carry on with your application.');
      await onSubmitted();
    } catch (err) {
      if (err.details?.field) setErrors({ [err.details.field === 'pan_number' ? 'pan' : err.details.field]: err.message });
      else toast.error(friendlyError(err, 'We could not submit your KYC.'));
    } finally {
      setBusy(false);
    }
  }

  if (ready) {
    return (
      <Card className="space-y-4 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Identity</h2>
            <p className="mt-0.5 text-xs text-slate">
              {verified
                ? 'Your KYC is verified.'
                : 'Your documents are with our team. You can finish the application while they are checked.'}
            </p>
          </div>
          <Badge tone={verified ? 'good' : 'warn'} dot>{verified ? 'Verified' : 'In review'}</Badge>
        </div>
        <div className="divide-y divide-line rounded-2xl border border-line px-4">
          <Row label="Name" value={eligibility.kyc_legal_name || '—'} />
          <Row label="PAN" value={eligibility.pan_last4 ? `XXXXXX${eligibility.pan_last4}` : '—'} mono />
          <Row label="Aadhaar" value={eligibility.aadhaar_last4 ? `XXXX XXXX ${eligibility.aadhaar_last4}` : 'Not given'} mono />
          {verified && <Row label="KYC level" value={eligibility.kyc_tier} />}
        </div>
        {verified && eligibility.kyc_tier !== 'FULL' && (
          <p className="text-xs text-slate">
            Basic KYC caps your limit at{' '}
            <span className="money font-medium text-ink">{money(eligibility.full_kyc_required_above, { decimals: 0 })}</span>.
            Full KYC (with Aadhaar) can be done later from your profile.
          </p>
        )}
        <StepFooter onNext={onNext} />
      </Card>
    );
  }

  return (
    <Card className="space-y-4 p-5 sm:p-6">
      <div>
        <h2 className="text-base font-semibold text-ink">Verify your identity</h2>
        <p className="mt-0.5 text-xs text-slate">
          Your PAN and Aadhaar, as a lender is required to collect. Your PAN is
          also how your credit score is found.
        </p>
      </div>

      {status === 'REJECTED' && eligibility.kyc_rejection_reason && (
        <p className="rounded-xl bg-red-50 px-3.5 py-3 text-xs text-alert">
          Your last submission was not approved: {eligibility.kyc_rejection_reason}
        </p>
      )}

      <Input
        label="Full name as on PAN"
        value={name}
        maxLength={200}
        onChange={(event) => { setName(event.target.value); setErrors((e) => ({ ...e, name: undefined })); }}
        error={errors.name}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
          label="PAN"
          placeholder="ABCDE1234F"
          value={pan}
          maxLength={10}
          className="money uppercase"
          onChange={(event) => { setPan(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '')); setErrors((e) => ({ ...e, pan: undefined })); }}
          error={errors.pan}
        />
        <Input
          label="Aadhaar"
          inputMode="numeric"
          placeholder="1234 5678 9012"
          value={aadhaar}
          maxLength={12}
          className="money"
          onChange={(event) => { setAadhaar(event.target.value.replace(/\D/g, '').slice(0, 12)); setErrors((e) => ({ ...e, aadhaar: undefined })); }}
          error={errors.aadhaar}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <FileField
          label="PAN card"
          file={files.pan}
          error={errors.panDoc}
          onPick={(file) => { setFiles((f) => ({ ...f, pan: file })); setErrors((e) => ({ ...e, panDoc: undefined })); }}
        />
        <FileField
          label="Aadhaar card"
          file={files.aadhaar}
          error={errors.aadhaarDoc}
          onPick={(file) => { setFiles((f) => ({ ...f, aadhaar: file })); setErrors((e) => ({ ...e, aadhaarDoc: undefined })); }}
        />
      </div>

      <Button variant="mint" size="lg" full loading={busy} onClick={submitKyc}>
        Submit KYC and continue
      </Button>
    </Card>
  );
}

/* ── Small pieces ───────────────────────────────────────────────────────── */

function StepBar({ steps, current, onPick }) {
  return (
    <ol className="mb-4 grid grid-cols-4 gap-1.5" aria-label="Application steps">
      {steps.map((item, index) => (
        <li key={item.key}>
          <button
            type="button"
            onClick={() => onPick(index)}
            disabled={index >= current}
            aria-current={index === current ? 'step' : undefined}
            className="w-full text-left disabled:cursor-default"
          >
            <span
              className={cx(
                'block h-1 rounded-full transition-colors',
                index < current ? 'bg-mint' : index === current ? 'bg-ink' : 'bg-line',
              )}
            />
            <span
              className={cx(
                'mt-1.5 block truncate text-2xs font-medium',
                index === current ? 'text-ink' : 'text-slate',
              )}
            >
              {item.label}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function StepFooter({ onBack, onNext, nextDisabled, hint }) {
  return (
    <div className="pt-1">
      <div className="flex gap-2">
        {onBack && <Button variant="outline" size="lg" onClick={onBack}>Back</Button>}
        <Button variant="mint" size="lg" full onClick={onNext} disabled={nextDisabled}>
          Continue
        </Button>
      </div>
      {hint && <p className="mt-2 text-center text-2xs text-slate">{hint}</p>}
    </div>
  );
}

function FileField({ label, file, error, onPick, prompt = 'Upload', className }) {
  const input = useRef(null);
  return (
    <div className={className}>
      {label && <p className="mb-1.5 text-sm font-medium text-ink">{label}</p>}
      <button
        type="button"
        onClick={() => input.current?.click()}
        className={cx(
          'flex w-full items-center justify-between gap-3 rounded-xl border border-dashed px-3.5 py-3 text-left transition-colors',
          file ? 'border-mint bg-mint-50/50' : 'border-line hover:border-ink/30',
          error && 'border-alert',
        )}
      >
        <span className="min-w-0 truncate text-sm text-ink">
          {file ? file.name : <span className="text-slate">{prompt} - PDF, JPG or PNG, up to 5 MB</span>}
        </span>
        <span className="shrink-0 text-xs font-semibold text-ink">{file ? 'Change' : 'Choose'}</span>
      </button>
      <input
        ref={input}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        className="hidden"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) onPick(picked);
          event.target.value = '';
        }}
      />
      {error && <p className="mt-1.5 text-xs text-alert">{error}</p>}
    </div>
  );
}
