import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { endpoints, newIdempotencyKey } from '../../api/client';
import { BankLogo } from '../../components/domain';
import { IconBank, IconPlus, PageHeader } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, Input, Row, Skeleton, cx,
} from '../../components/ui';
import { ErrorCard, friendlyError, outcomeUnknown } from '../../components/credit/CreditUI';
import { useFetch } from '../../hooks/useProfile';
import { useSessionDraft } from '../../hooks/useSessionDraft';
import { useToast } from '../../context/ToastContext';
import { money, sanitizeAmount } from '../../utils/format';
import { CategoryIcon, OtpBoxes } from './PayBillsUI';

/**
 * Pay Bills (Home -> Pay Bills).
 *
 *   bill -> bank -> summary -> confirm -> otp -> /pay-bills/:id (status)
 *
 * The step lives in the URL, so the browser's back button walks the steps the
 * same way the on-screen one does, and the draft survives leaving and coming
 * back. Nothing in the draft is secret: no card number, no OTP.
 *
 * This is a regulated credit transaction, not a transfer screen, and the page
 * is built to read like one. Every limit, fee and blocker is the server's; the
 * form only mirrors the server's checks so mistakes surface before submitting.
 * The OTP request is the first call that records anything, and the OTP is the
 * first thing that moves any credit.
 */

const STEPS = [
  { key: 'bill', label: 'Bill' },
  { key: 'bank', label: 'Bank' },
  { key: 'summary', label: 'Summary' },
  { key: 'confirm', label: 'Confirm' },
  { key: 'otp', label: 'Verify' },
];

const EMPTY = {
  category: '', provider: '', billRef: '', amount: '', purpose: '', purposeNote: '', bankId: '',
};

/* Development only - the server ignores these outside the simulated payout
   rail, and the rail refuses to simulate in production. */
const SANDBOX_OUTCOMES = [
  { value: 'SUCCESS', label: 'Bank confirms immediately' },
  { value: 'PENDING', label: 'Pending, then succeeds' },
  { value: 'FAIL', label: 'Bank declines the credit' },
  { value: 'PENDING_FAIL', label: 'Pending, then fails' },
  { value: 'REVERSE', label: 'Succeeds, then returned by bank' },
];

const BLOCKER_ACTIONS = {
  KYC: { label: 'Complete KYC', to: '/kyc' },
  APPLY: { label: 'Apply for credit', to: '/credit/apply' },
  CREDIT: { label: 'Go to my credit card', to: '/credit' },
  ADD_BANK: { label: 'Add Bank Account', to: '/banks/add' },
  PAY_CARD_BILL: { label: 'Pay card bill', to: '/credit/pay' },
};

const REF_PATTERN = /^[A-Za-z0-9\-/ ]{4,40}$/;

export default function PayBills() {
  const navigate = useNavigate();
  const toast = useToast();
  const { state: navState } = useLocation();
  const [params, setParams] = useSearchParams();
  const step = STEPS.some((s) => s.key === params.get('step')) ? params.get('step') : 'bill';
  const billId = params.get('id');

  const { data: info, loading, error: loadError, refetch } = useFetch(
    () => endpoints.billPay.eligibility(), [],
  );

  const [draft, update, clearDraft] = useSessionDraft('pay-bills', EMPTY);
  const [errors, setErrors] = useState({});
  const [consent, setConsent] = useState(false);
  const [quote, setQuote] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [otpMeta, setOtpMeta] = useState(navState?.otp || null);

  const attemptKey = useRef(null);

  const category = info?.categories?.find((c) => c.value === draft.category);
  const banks = info?.banks || [];
  const bank = banks.find((b) => b.bank_account_id === draft.bankId);
  const purposeLabel = info?.purposes?.find((p) => p.value === draft.purpose)?.label;
  const amount = Number(draft.amount || 0);

  // Blockers other than a missing bank stop the flow before it starts. A
  // missing bank is handled on the bank step, where adding one belongs.
  const hardBlockers = (info?.blockers || []).filter((b) => b.code !== 'NO_VERIFIED_BANK');

  // Default the destination to the primary verified account.
  useEffect(() => {
    if (banks.length && !banks.some((b) => b.bank_account_id === draft.bankId)) {
      update({ bankId: banks[0].bank_account_id });
    }
  }, [banks, draft.bankId, update]);

  // The server prices the bill. Re-asked whenever the amount settles.
  useEffect(() => {
    if (!(amount > 0)) { setQuote(null); return undefined; }
    let alive = true;
    const timer = setTimeout(() => {
      endpoints.billPay.quote(draft.amount)
        .then((res) => { if (alive) setQuote(res.data); })
        .catch(() => { if (alive) setQuote(null); });
    }, 250);
    return () => { alive = false; clearTimeout(timer); };
  }, [draft.amount, amount]);

  function edit(patch) {
    update(patch);
    // New details are a new attempt - the old key named a different request.
    attemptKey.current = null;
    setErrors({});
    setSubmitError(null);
    setConsent(false);
  }

  function chooseCategory(value) {
    if (value === draft.category) return;
    const option = info.categories.find((c) => c.value === value);
    edit({
      category: value,
      // A biller belongs to one category, so a new category starts clean.
      provider: '',
      // Pre-select the purpose that matches this bill.
      purpose: option.purposes.length === 1 ? option.purposes[0] : '',
      purposeNote: '',
    });
  }

  function go(next, extra = {}) {
    setParams({ step: next, ...extra });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* ── Validation, mirroring the server ─────────────────────────────── */

  function validateBill() {
    const found = {};
    if (!draft.category) found.category = 'Choose what kind of bill this is.';
    if (!draft.amount) found.amount = 'Enter the bill amount.';
    else if (!(amount > 0)) found.amount = 'Enter a valid amount.';
    else if (amount < info.min_amount) found.amount = `The smallest bill you can pay is ${money(info.min_amount)}.`;
    else if (info.kyc_tier !== 'FULL' && amount > info.full_kyc_above) {
      found.amount = `Bills above ${money(info.full_kyc_above)} need full KYC.`;
    } else if (amount > info.available_for_bills) {
      found.amount = `You can pay up to ${money(info.available_for_bills)} right now, including fees.`;
    }
    if (!REF_PATTERN.test(draft.billRef.trim())) {
      found.billRef = 'Enter the bill or reference number as printed (4-40 letters, digits, - or /).';
    }
    if (category?.providers.length ? !draft.provider : draft.provider.trim().length < 3) {
      found.provider = category?.providers.length ? 'Select the provider.' : 'Enter who the bill is from.';
    }
    if (!draft.purpose) found.purpose = 'Select the purpose of payment.';
    else if (category && !category.purposes.includes(draft.purpose)) {
      found.purpose = 'The purpose must match the bill you are paying.';
    }
    if (draft.purpose === 'OTHER' && draft.purposeNote.trim().length < 10) {
      found.purposeNote = 'Please describe the payment purpose (at least 10 characters).';
    }
    setErrors(found);
    return Object.keys(found).length === 0;
  }

  /* ── Submit: record the request and send the OTP ──────────────────── */

  async function requestOtp() {
    if (busy) return;
    if (!consent) {
      setErrors({ consent: 'Please confirm the declaration to continue.' });
      return;
    }
    setBusy(true);
    setSubmitError(null);
    if (!attemptKey.current) attemptKey.current = newIdempotencyKey();

    try {
      const res = await endpoints.billPay.create({
        category: draft.category,
        provider: draft.provider.trim(),
        bill_reference: draft.billRef.trim(),
        purpose: draft.purpose,
        purpose_note: draft.purpose === 'OTHER' ? draft.purposeNote.trim() : undefined,
        amount: draft.amount,
        bank_account_id: draft.bankId,
        consent: true,
      }, attemptKey.current);

      attemptKey.current = null;
      setOtpMeta(res.data.otp);
      go('otp', { id: res.data.bill_payment.bill_payment_id });
    } catch (err) {
      if (!outcomeUnknown(err)) attemptKey.current = null;
      setSubmitError(err);
      const field = err?.details?.field;
      if (field) {
        const map = { bill_reference: 'billRef', purpose_note: 'purposeNote', bank_account_id: 'bank' };
        setErrors({ [map[field] || field]: err.message });
      }
    } finally {
      setBusy(false);
    }
  }

  /* ── Loading and blocked states ───────────────────────────────────── */

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-5xl">
        <PageHeader title="Pay Bills" back="/home" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}
        </div>
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay Bills" back="/home" />
        <ErrorCard error={loadError} title="We could not load Pay Bills" onRetry={refetch} />
      </div>
    );
  }

  const header = (
    <PageHeader
      title="Pay Bills"
      subtitle="Pay eligible bills using your available credit and transfer the approved amount to your verified bank account."
      back={step === 'bill' ? '/home' : () => window.history.back()}
    />
  );

  if (hardBlockers.length) {
    const first = hardBlockers[0];
    const action = BLOCKER_ACTIONS[first.action];
    return (
      <div className="mx-auto w-full max-w-5xl animate-fade-up">
        {header}
        <CreditStats info={info} />
        <Card className="mx-auto mt-6 max-w-lg p-6 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-amber-50 text-warn ring-1 ring-amber-200">
            <CategoryIcon category="OTHER" className="h-6 w-6" />
          </span>
          <p className="mt-3 text-base font-semibold text-ink">Pay Bills is not available yet</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate">{first.message}</p>
          {hardBlockers.length > 1 && (
            <ul className="mx-auto mt-3 max-w-sm space-y-1 text-left text-xs text-slate">
              {hardBlockers.slice(1).map((b) => <li key={b.code}>• {b.message}</li>)}
            </ul>
          )}
          {action && (
            <Button variant="mint" size="lg" full className="mt-5" onClick={() => navigate(action.to)}>
              {action.label}
            </Button>
          )}
        </Card>
      </div>
    );
  }

  const index = STEPS.findIndex((s) => s.key === step);
  // A deep link past a step whose details are missing starts from the bill.
  const billReady = draft.category && draft.amount && draft.purpose;
  if (index > 0 && step !== 'otp' && !billReady) {
    return <Redirect to="bill" setParams={setParams} />;
  }

  return (
    <div className="mx-auto w-full max-w-5xl animate-fade-up">
      {header}
      <Stepper current={index} />

      {step === 'bill' && (
        <>
          <CreditStats info={info} />
          <BillStep
            info={info}
            draft={draft}
            category={category}
            errors={errors}
            quote={quote}
            onCategory={chooseCategory}
            onEdit={edit}
            onContinue={() => validateBill() && go('bank')}
          />
        </>
      )}

      {step === 'bank' && (
        <BankStep
          banks={banks}
          selected={draft.bankId}
          error={errors.bank}
          onSelect={(id) => edit({ bankId: id })}
          onAdd={() => navigate('/banks/add')}
          onContinue={() => {
            if (!bank) { setErrors({ bank: 'Select a verified bank account.' }); return; }
            go('summary');
          }}
        />
      )}

      {step === 'summary' && (
        <SummaryStep
          info={info}
          draft={draft}
          quote={quote}
          bank={bank}
          purposeLabel={purposeLabel}
          onContinue={() => go('confirm')}
        />
      )}

      {step === 'confirm' && (
        <ConfirmStep
          info={info}
          draft={draft}
          category={category}
          quote={quote}
          bank={bank}
          purposeLabel={purposeLabel}
          consent={consent}
          busy={busy}
          error={errors.consent}
          submitError={submitError}
          onConsent={(value) => { setConsent(value); setErrors({}); }}
          onContinue={requestOtp}
          onCancel={() => {
            clearDraft();
            toast.success('Cancelled. Nothing was charged.');
            navigate('/home', { replace: true });
          }}
        />
      )}

      {step === 'otp' && billId && (
        <OtpStep
          billId={billId}
          meta={otpMeta}
          maskedMobile={otpMeta?.masked_mobile || info.masked_mobile}
          sandbox={info.sandbox}
          draft={draft}
          quote={quote}
          bank={bank}
          onMeta={setOtpMeta}
          onDone={(bill) => navigate(`/pay-bills/${bill.bill_payment_id}`, {
            replace: true, state: { fresh: true, bill },
          })}
          onRestart={() => go('confirm')}
        />
      )}
    </div>
  );
}

function Redirect({ to, setParams }) {
  useEffect(() => { setParams({ step: to }, { replace: true }); }, [to, setParams]);
  return null;
}

/* ── Pieces ─────────────────────────────────────────────────────────────── */

function Stepper({ current }) {
  return (
    <nav aria-label="Pay Bills progress" className="-mx-1 mb-6 overflow-x-auto px-1">
      <ol className="flex min-w-max items-center gap-1.5 sm:min-w-0">
        {STEPS.map((s, i) => {
          const done = i < current;
          const here = i === current;
          return (
            <li key={s.key} className="flex items-center gap-1.5 sm:flex-1">
              <span
                aria-current={here ? 'step' : undefined}
                className={cx(
                  'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs font-semibold',
                  done && 'border-mint-200 bg-mint-50 text-mint-800',
                  here && 'border-ink bg-ink text-white',
                  !done && !here && 'border-line bg-canvas text-slate-light',
                )}
              >
                <span className="money">{i + 1}</span>
                {s.label}
              </span>
              {i < STEPS.length - 1 && (
                <span aria-hidden="true" className={cx('hidden h-px flex-1 sm:block', done ? 'bg-mint-300' : 'bg-line')} />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function CreditStats({ info }) {
  const stats = [
    { label: 'Available Credit', value: money(info.available_credit), tone: 'mint' },
    { label: 'Credit Limit', value: money(info.credit_limit, { decimals: 0 }) },
    { label: 'Available for Bill Payment', value: money(info.available_for_bills), tone: 'ink' },
    { label: 'Processing Fee', value: `${info.fee_percent}% + GST`, hint: `GST ${info.gst_percent}% on the fee only` },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map((s) => (
        <div key={s.label} className="rounded-2xl border border-line/80 bg-canvas p-4 shadow-card">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">{s.label}</p>
          <p className={cx('money mt-1.5 text-lg font-bold tracking-tight sm:text-xl',
            s.tone === 'mint' ? 'text-mint-700' : 'text-ink')}
          >
            {s.value}
          </p>
          {s.hint && <p className="mt-0.5 text-2xs text-slate">{s.hint}</p>}
        </div>
      ))}
    </div>
  );
}

function Select({ label, value, onChange, options, placeholder, error, id }) {
  return (
    <div className="w-full">
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      <div className={cx(
        'relative flex h-12 items-center rounded-xl border bg-canvas transition-all duration-base ease-glide',
        error ? 'border-alert ring-2 ring-alert/15'
          : 'border-line focus-within:border-ink/40 focus-within:ring-2 focus-within:ring-mint/20',
      )}
      >
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          className={cx('h-full w-full appearance-none bg-transparent pl-3.5 pr-10 text-[15px] outline-none',
            value ? 'text-ink' : 'text-slate-light')}
        >
          <option value="" disabled>{placeholder}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
          ))}
        </select>
        <svg viewBox="0 0 20 20" className="pointer-events-none absolute right-3.5 h-4 w-4 text-slate" fill="none" aria-hidden="true">
          <path d="M5 8l5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      {error && <p className="mt-1.5 animate-slide-down text-xs text-alert">{error}</p>}
    </div>
  );
}

function InfoNote({ children, tone = 'mint' }) {
  return (
    <div className={cx(
      'flex gap-2.5 rounded-xl border px-3.5 py-3 text-xs leading-relaxed',
      tone === 'mint' ? 'border-mint-200 bg-mint-50/70 text-mint-900/80' : 'border-amber-200 bg-amber-50 text-amber-800',
    )}
    >
      <svg viewBox="0 0 24 24" className="mt-px h-4 w-4 shrink-0" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 11v5M12 8h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span>{children}</span>
    </div>
  );
}

/* ── Step 1: bill ───────────────────────────────────────────────────────── */

function BillStep({ info, draft, category, errors, quote, onCategory, onEdit, onContinue }) {
  const purposeOptions = info.purposes.map((p) => ({
    ...p,
    // Offered in full, as the spec lists them, but only a purpose that
    // matches the bill can be chosen - the server refuses the rest.
    disabled: category ? !category.purposes.includes(p.value) : false,
  }));

  return (
    <div className="mt-6 space-y-6">
      <section>
        <h2 className="mb-3 px-1 text-base font-bold tracking-tight text-ink">Select Bill Category</h2>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4">
          {info.categories.map((c) => {
            const selected = draft.category === c.value;
            return (
              <button
                key={c.value}
                type="button"
                aria-pressed={selected}
                onClick={() => onCategory(c.value)}
                className={cx(
                  'group flex items-center gap-3 rounded-2xl border p-3.5 text-left transition-all duration-base ease-glide active:scale-[0.98]',
                  selected
                    ? 'border-mint bg-mint-50/60 ring-2 ring-mint/25 shadow-card'
                    : 'border-line/80 bg-canvas hover:border-mint-500/30 hover:bg-mist/40 hover:shadow-card',
                )}
              >
                <span className={cx(
                  'grid h-10 w-10 shrink-0 place-items-center rounded-xl transition-all duration-base',
                  selected ? 'bg-mint text-ink' : 'bg-mist text-slate group-hover:bg-mint group-hover:text-ink',
                )}
                >
                  <CategoryIcon category={c.value} />
                </span>
                <span className="min-w-0 text-xs font-semibold leading-snug text-ink sm:text-sm">{c.label}</span>
              </button>
            );
          })}
        </div>
        {errors.category && <p className="mt-2 px-1 text-xs text-alert">{errors.category}</p>}
      </section>

      {category && (
        <Card className="animate-fade-up p-5 sm:p-6">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-mint text-ink">
              <CategoryIcon category={category.value} />
            </span>
            <div>
              <p className="text-base font-bold text-ink">{category.label}</p>
              <p className="text-2xs text-slate">Enter the details exactly as they appear on your bill.</p>
            </div>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <Input
              label="Bill Amount"
              prefix="₹"
              inputMode="decimal"
              placeholder="10,000"
              value={draft.amount}
              onChange={(e) => onEdit({ amount: sanitizeAmount(e.target.value) })}
              error={errors.amount}
              hint={quote
                ? `Credit utilised ${money(quote.total)} incl. ${money(quote.fee)} fee + ${money(quote.gst)} GST.`
                : `Up to ${money(info.available_for_bills)} available for bill payment.`}
            />

            <Input
              label="Bill / Reference Number"
              placeholder="Enter bill or reference number"
              value={draft.billRef}
              maxLength={40}
              autoComplete="off"
              onChange={(e) => onEdit({ billRef: e.target.value })}
              error={errors.billRef}
            />

            {category.providers.length ? (
              <Select
                id="pb-provider"
                label="Bill Provider / Merchant"
                placeholder="Select provider"
                value={draft.provider}
                onChange={(value) => onEdit({ provider: value })}
                options={category.providers.map((p) => ({ value: p, label: p }))}
                error={errors.provider}
              />
            ) : (
              <Input
                label="Bill Provider / Merchant"
                placeholder="Who is the bill from?"
                value={draft.provider}
                maxLength={120}
                onChange={(e) => onEdit({ provider: e.target.value })}
                error={errors.provider}
              />
            )}

            <Select
              id="pb-purpose"
              label="Purpose of Payment"
              placeholder="Select purpose"
              value={draft.purpose}
              onChange={(value) => onEdit({ purpose: value, purposeNote: value === 'OTHER' ? draft.purposeNote : '' })}
              options={purposeOptions}
              error={errors.purpose}
            />
          </div>

          {draft.purpose === 'OTHER' && (
            <div className="mt-5">
              <label htmlFor="pb-note" className="mb-1.5 block text-sm font-medium text-ink">
                Please describe the payment purpose
              </label>
              <textarea
                id="pb-note"
                rows={3}
                maxLength={200}
                value={draft.purposeNote}
                onChange={(e) => onEdit({ purposeNote: e.target.value })}
                placeholder="e.g. Annual society maintenance charges for flat 402"
                aria-invalid={Boolean(errors.purposeNote)}
                className={cx(
                  'w-full resize-none rounded-xl border bg-canvas px-3.5 py-3 text-[15px] text-ink outline-none transition-all placeholder:text-slate-light',
                  errors.purposeNote ? 'border-alert ring-2 ring-alert/15' : 'border-line focus:border-ink/40 focus:ring-2 focus:ring-mint/20',
                )}
              />
              <p className={cx('mt-1.5 text-xs', errors.purposeNote ? 'text-alert' : 'text-slate')}>
                {errors.purposeNote || `${draft.purposeNote.length}/200`}
              </p>
            </div>
          )}

          <div className="mt-5">
            <InfoNote>
              Use Pay Bills only for genuine eligible expenses. Your transaction may be subject to
              eligibility checks, applicable fees, limits, and verification.
            </InfoNote>
          </div>

          <div className="mt-6 flex justify-end">
            <Button variant="mint" size="lg" className="w-full sm:w-auto sm:min-w-[200px]" onClick={onContinue}>
              Continue
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Step 2: bank ───────────────────────────────────────────────────────── */

function BankStep({ banks, selected, error, onSelect, onAdd, onContinue }) {
  return (
    <div className="mx-auto max-w-2xl">
      <h2 className="px-1 text-base font-bold tracking-tight text-ink">Transfer To</h2>
      <p className="mb-4 px-1 text-xs text-slate">
        Select Bank Account. Only your own accounts verified by penny drop can receive a payout.
      </p>

      {banks.length === 0 ? (
        <Card className="border-dashed py-8 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-mist text-slate">
            <IconBank className="h-6 w-6" />
          </span>
          <p className="mt-3 text-base font-semibold text-ink">No verified bank account available</p>
          <p className="mx-auto mt-1 max-w-xs text-sm text-slate">
            Add and verify an account in your name to receive bill payments.
          </p>
          <Button variant="mint" size="md" className="mt-5" onClick={onAdd}>
            <IconPlus className="h-4 w-4" /> Add Bank Account
          </Button>
        </Card>
      ) : (
        <div className="space-y-2.5" role="radiogroup" aria-label="Bank account">
          {banks.map((b) => {
            const active = b.bank_account_id === selected;
            return (
              <button
                key={b.bank_account_id}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onSelect(b.bank_account_id)}
                className={cx(
                  'flex w-full items-center gap-3.5 rounded-2xl border bg-canvas p-4 text-left transition-all duration-base ease-glide active:scale-[0.99]',
                  active ? 'border-mint ring-2 ring-mint/25 shadow-card' : 'border-line/80 hover:border-mint-500/30 hover:shadow-card',
                )}
              >
                <span className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-canvas">
                  <BankLogo bankName={b.bank_name} size="sm" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-semibold text-ink">{b.bank_name}</p>
                    {b.is_primary && <Badge tone="neutral">Primary Account</Badge>}
                  </div>
                  <p className="money mt-0.5 text-xs tracking-wider text-slate">XXXX XXXX {b.account_last4}</p>
                </div>
                <Badge tone="good" dot className="shrink-0">Verified</Badge>
                <span className={cx(
                  'grid h-5 w-5 shrink-0 place-items-center rounded-full border-2',
                  active ? 'border-mint bg-mint' : 'border-line',
                )}
                >
                  {active && <span className="h-2 w-2 rounded-full bg-ink" />}
                </span>
              </button>
            );
          })}

          <button
            type="button"
            onClick={onAdd}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line p-3.5 text-sm font-medium text-slate transition-all hover:border-mint-600/40 hover:bg-mint-50/40 hover:text-ink"
          >
            <IconPlus className="h-4 w-4" /> Add Bank Account
          </button>
        </div>
      )}

      {error && <p className="mt-3 text-xs text-alert">{error}</p>}

      {banks.length > 0 && (
        <Button variant="mint" size="lg" full className="mt-6" onClick={onContinue}>
          Continue
        </Button>
      )}
    </div>
  );
}

/* ── Step 3: summary ────────────────────────────────────────────────────── */

function SummaryCard({ info, quote, bank, purposeLabel, draft }) {
  const after = quote ? Math.max(0, info.available_credit - quote.total) : null;
  return (
    <Card className="overflow-hidden !p-0">
      <div className="border-b border-line bg-mist/50 px-5 py-3.5">
        <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Payment Summary</p>
      </div>
      <div className="divide-y divide-line px-5 py-1">
        <Row label="Bill Amount" value={money(draft.amount)} mono />
        <Row
          label={`Processing Fee${quote ? ` (${quote.fee_percent}%)` : ''}`}
          value={quote ? money(quote.fee) : '…'}
          mono
        />
        <Row
          label={`Applicable Taxes${quote ? ` (GST ${quote.gst_percent}% on fee)` : ''}`}
          value={quote ? money(quote.gst) : '…'}
          mono
        />
      </div>
      <div className="mx-5 my-3 rounded-2xl bg-ink px-5 py-4 text-white">
        <p className="text-2xs font-semibold uppercase tracking-wider text-white/60">Total Credit Utilized</p>
        <p className="money mt-1 text-3xl font-extrabold tracking-tight text-mint">
          {quote ? money(quote.total) : '…'}
        </p>
      </div>
      <div className="divide-y divide-line px-5 pb-2">
        <Row label="Bank Account" value={bank ? `${bank.bank_name} •••• ${bank.account_last4}` : '-'} />
        <Row label="Purpose" value={purposeLabel || '-'} />
      </div>
      <div className="border-t border-line bg-mint-50/50 px-5 py-3 text-sm text-ink">
        Available credit after transaction:{' '}
        <span className="money font-bold">{after != null ? money(after) : '…'}</span>
      </div>
    </Card>
  );
}

function SummaryStep({ info, draft, quote, bank, purposeLabel, onContinue }) {
  return (
    <div className="mx-auto max-w-lg">
      <SummaryCard info={info} quote={quote} bank={bank} purposeLabel={purposeLabel} draft={draft} />
      <p className="mt-3 px-1 text-2xs leading-relaxed text-slate">
        The fee and GST are charged to your credit line with the bill and appear on your
        statement. If the payment does not complete, the full amount is restored.
      </p>
      <Button variant="mint" size="lg" full className="mt-5" disabled={!quote} onClick={onContinue}>
        Continue
      </Button>
    </div>
  );
}

/* ── Step 4: review & confirm ───────────────────────────────────────────── */

function ConfirmStep({
  info, draft, category, quote, bank, purposeLabel, consent, busy, error, submitError,
  onConsent, onContinue, onCancel,
}) {
  return (
    <div className="mx-auto max-w-lg">
      <h2 className="px-1 text-lg font-bold tracking-tight text-ink">Review &amp; Confirm</h2>
      <p className="mb-4 px-1 text-sm text-slate">
        You&apos;re about to use your available credit for an eligible bill payment.
      </p>

      <Card className="divide-y divide-line py-1">
        <Row label="Bill category" value={category?.label} />
        <Row label="Bill provider" value={draft.provider} />
        <Row label="Bill/reference number" value={draft.billRef} mono />
        <Row label="Bill amount" value={money(draft.amount)} mono />
        <Row label="Processing fee" value={quote ? money(quote.fee) : '…'} mono />
        <Row label="Taxes (GST on fee)" value={quote ? money(quote.gst) : '…'} mono />
        <div className="flex items-baseline justify-between gap-4 py-3">
          <span className="text-sm font-semibold text-ink">Total amount</span>
          <span className="money text-xl font-extrabold text-ink">{quote ? money(quote.total) : '…'}</span>
        </div>
        <Row label="Destination bank account" value={bank ? `${bank.bank_name} •••• ${bank.account_last4}` : '-'} />
        <Row label="Purpose" value={purposeLabel + (draft.purpose === 'OTHER' ? ` - ${draft.purposeNote}` : '')} />
      </Card>

      <div className="mt-4 space-y-2 rounded-2xl border border-line bg-mist/50 p-4 text-2xs leading-relaxed text-slate">
        <p className="text-xs font-semibold text-ink">Before you confirm</p>
        <p>• The total is drawn from your CashU credit line and is repayable with your card statement. It is not cash and is not free of charge.</p>
        <p>• Funds are sent only to your own verified bank account, for the bill you have declared.</p>
        <p>• Payments are subject to eligibility checks, daily limits and verification, and may be held for review.</p>
        <p>• If the payment fails or is returned by the bank, the full amount - fee and GST included - is restored to your credit line.</p>
      </div>

      <label className={cx(
        'mt-4 flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition-colors',
        consent ? 'border-mint bg-mint-50/50' : error ? 'border-alert' : 'border-line hover:border-ink/20',
      )}
      >
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => onConsent(e.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 accent-[#00C896]"
        />
        <span className="text-sm leading-relaxed text-ink">{info.consent_text}</span>
      </label>
      {error && <p className="mt-2 text-xs text-alert">{error}</p>}

      {submitError && (
        <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-alert" role="alert">
          <p className="font-medium">{friendlyError(submitError)}</p>
          {submitError.recovery && <p className="mt-1 text-xs">{submitError.recovery}</p>}
        </div>
      )}

      <div className="mt-5 flex flex-col-reverse gap-2.5 sm:flex-row">
        <Button variant="outline" size="lg" className="sm:flex-1" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant="mint" size="lg" className="sm:flex-1" onClick={onContinue} loading={busy} disabled={!quote}>
          {submitError && outcomeUnknown(submitError) ? 'Try again safely' : 'Continue'}
        </Button>
      </div>
    </div>
  );
}

/* ── Step 5: OTP ────────────────────────────────────────────────────────── */

function OtpStep({ billId, meta, maskedMobile, sandbox, draft, quote, bank, onMeta, onDone, onRestart }) {
  const toast = useToast();
  const length = meta?.length || 6;
  const [digits, setDigits] = useState(() => (
    meta?.debug_otp ? String(meta.debug_otp).split('') : Array(length).fill('')
  ));
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(30);
  const [outcome, setOutcome] = useState('SUCCESS');
  const code = digits.join('');

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const summary = useMemo(() => ({
    total: quote?.total, bank: bank ? `${bank.bank_name} •••• ${bank.account_last4}` : null,
  }), [quote, bank]);

  async function verify(event) {
    event?.preventDefault();
    if (code.length !== length || busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await endpoints.billPay.confirm(billId, {
        otp: code,
        sandbox_outcome: sandbox ? outcome : undefined,
      });
      onDone(res.data);
    } catch (err) {
      setError(friendlyError(err));
      setErrorCode(err.code);
      setDigits(Array(length).fill(''));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (resending || cooldown > 0) return;
    setResending(true);
    try {
      const res = await endpoints.billPay.resendOtp(billId);
      onMeta(res.data.otp);
      setDigits(res.data.otp?.debug_otp ? String(res.data.otp.debug_otp).split('') : Array(length).fill(''));
      setCooldown(30);
      setError('');
      toast.success('A new OTP is on its way.');
    } catch (err) {
      toast.error(friendlyError(err));
      setErrorCode(err.code);
    } finally {
      setResending(false);
    }
  }

  const expired = errorCode === 'REQUEST_EXPIRED' || errorCode === 'CONFLICT';

  return (
    <form onSubmit={verify} className="mx-auto max-w-md">
      <Card className="p-6 sm:p-7">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-mint-50 text-mint-700 ring-1 ring-mint-200">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
            <path d="M8 10V7a4 4 0 018 0v3" />
          </svg>
        </span>
        <h2 className="mt-4 text-center text-xl font-bold tracking-tight text-ink">Verify Payment</h2>
        <p className="mt-1 text-center text-sm text-slate">Enter OTP to confirm this transaction</p>
        <p className="mt-1 text-center text-xs text-slate">
          Sent to <span className="money font-semibold text-ink">+91 {maskedMobile}</span>
        </p>

        {summary.total != null && (
          <div className="mt-5 flex items-center justify-between rounded-xl bg-mist/60 px-4 py-3 text-sm">
            <span className="text-slate">{draft.provider || 'Bill payment'}</span>
            <span className="money font-bold text-ink">{money(summary.total)}</span>
          </div>
        )}

        <div className="mt-6">
          <OtpBoxes digits={digits} onChange={(d) => { setDigits(d); setError(''); }} error={error} disabled={busy} length={length} />
        </div>
        {error && <p className="mt-3 text-center text-sm text-alert" role="alert">{error}</p>}

        {sandbox && (
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3">
            <label htmlFor="pb-sim" className="block text-2xs font-semibold uppercase tracking-wider text-amber-800">
              Development build - simulated bank payout
            </label>
            <select
              id="pb-sim"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              className="mt-1.5 h-9 w-full rounded-lg border border-amber-200 bg-canvas px-2 text-xs text-ink outline-none"
            >
              {SANDBOX_OUTCOMES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        )}

        {expired ? (
          <Button type="button" variant="mint" size="lg" full className="mt-6" onClick={onRestart}>
            Start again
          </Button>
        ) : (
          <Button type="submit" variant="mint" size="lg" full className="mt-6"
            disabled={code.length !== length} loading={busy}
          >
            Verify &amp; Continue
          </Button>
        )}

        <div className="mt-4 text-center text-sm">
          {cooldown > 0 ? (
            <p className="text-slate">
              Resend OTP in <span className="money font-medium text-ink">0:{String(cooldown).padStart(2, '0')}</span>
            </p>
          ) : (
            <button type="button" onClick={resend} disabled={resending}
              className="font-semibold text-mint-700 hover:text-mint-800 disabled:opacity-50"
            >
              {resending ? 'Sending…' : 'Resend OTP'}
            </button>
          )}
        </div>
      </Card>
      <p className="mt-3 px-2 text-center text-2xs leading-relaxed text-slate">
        CashU will never ask for your OTP by phone, SMS or email. Nothing is charged until the OTP is verified.
        {summary.bank && <> Paying to {summary.bank}.</>}
      </p>
    </form>
  );
}
