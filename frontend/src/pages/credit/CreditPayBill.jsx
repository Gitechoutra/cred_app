import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { endpoints, newIdempotencyKey } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { PaymentMethodPicker } from '../../components/payments/PaymentMethods';
import { Badge, Button, Card, Input, Sheet, Skeleton, cx } from '../../components/ui';
import {
  ErrorCard, ProcessingPanel, friendlyError, outcomeUnknown,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useReturnTo } from '../../hooks/useNavHistory';
import { useFetch } from '../../hooks/useProfile';
import { useRazorpay } from '../../hooks/useRazorpay';
import { date, money, sanitizeAmount } from '../../utils/format';

/**
 * Pay the card bill.
 *
 * The rule this screen is built around: **the browser never decides that a
 * payment succeeded.** Opening a payment restores nothing. Checkout's success
 * handler means "something happened, go and ask", and the server verifies the
 * signature and re-reads the payment from the gateway before a rupee of credit
 * comes back. Every branch below - paid, failed, dismissed, timed out, network
 * gone - ends in a server call, never in a local assumption.
 *
 * Two steps, amount then method, with the step in the URL so the browser's back
 * button walks them like the on-screen one does. The result is the transaction
 * receipt, which replaces the method step in history: going back from a receipt
 * must not land on a Pay button for a bill that was just paid.
 *
 * Presets are the three decisions people actually make: clear it, pay the
 * minimum, or something in between. The minimum is the server's number, never a
 * percentage recomputed here.
 */

const UPI = ['UPI_INTENT', 'UPI_COLLECT'];

/* Development only - the server refuses these outside the simulated gateway,
   and never offers the simulator in production. They let every failure path be
   walked through by hand. */
const SANDBOX_OUTCOMES = [
  { value: 'APPROVE', label: 'Approve payment', hint: 'The bank confirms it', tone: 'mint' },
  { value: 'DECLINE', label: 'Decline at the bank', hint: 'Payment fails', tone: 'outline' },
  { value: 'ABANDON', label: 'Close checkout', hint: 'Payer backs out - cancelled', tone: 'outline' },
  { value: 'TIMEOUT', label: 'Gateway timeout', hint: 'Gateway does not respond', tone: 'outline' },
];

export default function CreditPayBill() {
  const navigate = useNavigate();
  const returnTo = useReturnTo();
  const toast = useToast();
  const razorpay = useRazorpay();
  const [params, setParams] = useSearchParams();
  const choosingMethod = params.get('step') === 'method';

  const { data: current, loading, error: loadError, refetch } = useFetch(
    () => endpoints.credit.currentStatement(), [],
  );
  const { data: methods } = useFetch(() => endpoints.credit.billMethods(), []);

  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState('UPI_INTENT');
  const [upiApp, setUpiApp] = useState('google_pay');
  const [error, setError] = useState('');
  const [failure, setFailure] = useState(null);
  const [stage, setStage] = useState(null); // null | 'opening' | 'awaiting' | 'verifying'
  const [sandboxOpen, setSandboxOpen] = useState(false);
  const [pendingBusy, setPendingBusy] = useState(false);

  /* The key is per attempt: same amount, same method, same key, until the
     server gives a definite answer. A retry after a dropped response replays
     the payment instead of opening a second order. */
  const attemptKey = useRef(null);
  const attemptOf = useRef('');
  const inFlight = useRef(false);
  const mounted = useRef(true);
  // Set true on every mount, not only initialised true: StrictMode mounts,
  // unmounts and remounts in development, and a ref only ever cleared left
  // this screen believing it was gone - it verified the payment and then never
  // showed the result.
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const account = current?.account;
  const statement = current?.latest_statement;
  const pending = current?.pending_payment;
  const outstanding = Number(account?.current_outstanding || 0);
  const minimum = Number(statement?.minimum_outstanding || 0);
  const payable = Number(amount || 0);
  const minimumAmount = Number(methods?.minimum_amount || 1);

  const permitted = methods?.permitted || [];
  const chosen = permitted.find((m) => m.mode === mode);
  const simulated = Boolean(methods?.sandbox) && chosen?.provider === 'SANDBOX';

  const presets = [
    outstanding > 0 && {
      key: 'full', label: 'Total outstanding', hint: 'Clears everything you owe', value: outstanding,
    },
    minimum > 0 && minimum < outstanding && {
      key: 'minimum',
      label: 'Minimum due',
      hint: statement?.due_date ? `Due ${date(statement.due_date)}` : null,
      value: minimum,
    },
  ].filter(Boolean);

  function validate() {
    if (!amount) return 'Enter an amount to pay.';
    if (!Number.isFinite(payable) || payable <= 0) return 'Enter a valid amount.';
    if (payable < minimumAmount) return `The smallest payment is ${money(minimumAmount)}.`;
    if (payable > outstanding) return `You owe ${money(outstanding)}. Enter that or less.`;
    return '';
  }

  function toMethodStep() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setParams({ step: 'method' });
  }

  function showReceipt(txn) {
    navigate(`/credit/transactions/${txn.credit_transaction_id}`, {
      replace: true,
      state: { fresh: true },
    });
  }

  /**
   * Take whatever happened to the server and show what it decides.
   *
   * `payload` is Checkout's signed success handler, when there is one. With
   * `cancel`, the server checks the gateway before cancelling anything - the
   * sheet closed after authorising is a paid bill, not a cancelled one.
   */
  async function resolve(txn, { payload, cancel = false } = {}) {
    setStage('verifying');
    try {
      const response = cancel
        ? await endpoints.credit.cancelBill(txn.credit_transaction_id)
        : await endpoints.credit.verifyBill(txn.credit_transaction_id, payload || {});
      attemptKey.current = null;
      if (mounted.current) showReceipt(response.data.transaction);
    } catch (err) {
      // The check itself failed, not the payment. It may well have gone
      // through, so it is not reported as failed; the receipt keeps asking.
      toast.error(friendlyError(err, 'We could not confirm the payment yet.'));
      if (mounted.current) showReceipt(txn);
    }
  }

  async function pay(sandboxOutcome) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSandboxOpen(false);
    setFailure(null);
    setStage('opening');

    const signature = `${payable}|${mode}`;
    if (!attemptKey.current || attemptOf.current !== signature) {
      attemptKey.current = newIdempotencyKey();
      attemptOf.current = signature;
    }

    let txn = null;
    try {
      const response = await endpoints.credit.payBill({
        amount,
        payment_method: mode,
        statement_id: statement?.statement_id,
        sandbox_outcome: simulated ? sandboxOutcome : undefined,
      }, attemptKey.current);

      txn = response.data.transaction;
      const checkout = response.data.checkout || {};

      // A replayed key whose payment already finished.
      if (txn.is_terminal) {
        attemptKey.current = null;
        showReceipt(txn);
        return;
      }

      if (checkout.provider === 'RAZORPAY' && checkout.key) {
        setStage('awaiting');
        let result;
        try {
          result = await razorpay.open({
            key: checkout.key,
            order_id: checkout.order_id,
            // From the server's order, never from this screen. A browser that
            // could choose the amount could pay one rupee against the bill.
            amount: checkout.amount_paise,
            currency: checkout.currency || 'INR',
            name: 'CashU',
            description: 'Credit card bill payment',
            prefill: {
              ...(methods?.prefill || {}),
              ...(UPI.includes(mode) ? { method: 'upi' } : {}),
            },
            notes: { credit_transaction_id: txn.credit_transaction_id },
            theme: { color: '#00F5B8' },
          });
        } catch (openError) {
          // Checkout never opened - blocked script or no network. Nothing was
          // charged, so cancel rather than leave it processing.
          toast.error(openError.message);
          await resolve(txn, { cancel: true });
          return;
        }

        if (result.outcome === 'paid') {
          await resolve(txn, {
            payload: {
              razorpay_payment_id: result.response.razorpay_payment_id,
              razorpay_order_id: result.response.razorpay_order_id,
              razorpay_signature: result.response.razorpay_signature,
            },
          });
        } else if (result.outcome === 'failed') {
          await resolve(txn);
        } else {
          await resolve(txn, { cancel: true });
        }
        return;
      }

      // The simulated gateway, or a rail with no in-page checkout: the server
      // asks the gateway directly.
      await resolve(txn, { cancel: sandboxOutcome === 'ABANDON' });
    } catch (err) {
      if (!mounted.current) return;
      const recorded = err?.details?.transaction;

      if (err.code === 'CONFLICT') {
        // A payment is already in flight. Show it, rather than open another.
        toast.info(err.message);
        attemptKey.current = null;
        setStage(null);
        refetch();
        return;
      }

      if (recorded && recorded.status === 'FAILED') {
        // The gateway could not be reached or timed out. Recorded, nothing
        // charged, and a retry is a fresh attempt.
        attemptKey.current = null;
        setFailure({ ...err, transaction: recorded });
        setStage(null);
        return;
      }

      if (txn) {
        // The order opened but something after it broke. Ask the server.
        await resolve(txn);
        return;
      }

      if (!outcomeUnknown(err)) attemptKey.current = null;
      setFailure(err);
      setStage(null);
    } finally {
      inFlight.current = false;
    }
  }

  function onPay() {
    if (simulated) setSandboxOpen(true);
    else pay();
  }

  async function checkPending() {
    setPendingBusy(true);
    try {
      const response = await endpoints.credit.verifyBill(pending.credit_transaction_id);
      const txn = response.data.transaction;
      if (txn.status === 'PROCESSING') {
        toast.info('Still waiting for your bank to confirm.');
      } else {
        showReceipt(txn);
      }
    } catch (err) {
      toast.error(friendlyError(err));
    } finally {
      setPendingBusy(false);
    }
  }

  async function cancelPending() {
    setPendingBusy(true);
    try {
      const response = await endpoints.credit.cancelBill(pending.credit_transaction_id);
      const txn = response.data.transaction;
      if (txn.status === 'PROCESSING') {
        toast.info('Your bank is still working on this payment, so it cannot be cancelled yet.');
      } else {
        toast.info(response.message);
        refetch();
      }
    } catch (err) {
      toast.error(friendlyError(err));
    } finally {
      setPendingBusy(false);
    }
  }

  /* ── Loading and error ──────────────────────────────────────────────── */

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay your bill" back="/credit" />
        <Skeleton className="h-36 w-full rounded-2xl" />
        <Skeleton className="mt-4 h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (!current) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay your bill" back="/credit" />
        <ErrorCard error={loadError} title="We could not load your bill" onRetry={refetch} />
      </div>
    );
  }

  if (stage) {
    return (
      <ProcessingPanel
        title={
          stage === 'awaiting' ? 'Complete the payment in your app'
            : stage === 'opening' ? 'Connecting to the payment gateway'
              : 'Confirming your payment'
        }
        subtitle={
          stage === 'awaiting'
            ? 'Approve the request, then come back here. Do not pay twice.'
            : 'Checking with your bank. This takes a moment - please do not close this page.'
        }
      />
    );
  }

  /* ── A payment already in flight ────────────────────────────────────── */
  if (pending) {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Pay your bill" back="/credit" />
        <Card className="p-6 text-center">
          <Badge tone="warn" dot>Processing</Badge>
          <p className="money mt-3 text-3xl font-bold text-ink">{money(pending.amount)}</p>
          <p className="mt-1 text-sm font-medium text-ink">A payment is already on its way</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate">
            Your credit comes back as soon as your bank confirms it. Paying again
            now could charge you twice.
          </p>
          <div className="mt-5 space-y-2">
            <Button variant="mint" size="lg" full loading={pendingBusy} onClick={checkPending}>
              Check status
            </Button>
            <Button variant="ghost" size="lg" full disabled={pendingBusy} onClick={cancelPending}>
              I did not pay - cancel it
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  /* ── Nothing to pay ─────────────────────────────────────────────────── */
  if (outstanding <= 0) {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Pay your bill" back="/credit" />
        <Card className="p-6 text-center">
          <Badge tone="good" dot>All clear</Badge>
          <p className="mt-3 text-base font-semibold text-ink">Nothing outstanding</p>
          <p className="mt-1 text-sm text-slate">
            Your full {money(account?.credit_limit)} limit is available.
          </p>
          <Button variant="outline" size="lg" full className="mt-5" onClick={() => returnTo('/credit')}>
            Back to my card
          </Button>
        </Card>
      </div>
    );
  }

  /* ── Method ─────────────────────────────────────────────────────────── */
  if (choosingMethod && payable > 0 && !validate()) {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Payment method" subtitle="How would you like to pay?" back="/credit/pay" />

        {failure && (
          <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-alert" role="alert">
            <p className="font-medium">{friendlyError(failure)}</p>
            {failure.recovery && <p className="mt-1 text-xs">{failure.recovery}</p>}
            {failure.transaction?.reference && (
              <p className="mt-2 text-2xs text-alert/80">Reference {failure.transaction.reference}</p>
            )}
          </div>
        )}

        <PaymentMethodPicker
          amount={payable}
          caption={statement?.due_date ? `Statement due ${date(statement.due_date)}` : 'Credit card bill'}
          methods={permitted}
          prohibited={methods?.prohibited || []}
          upiApps={methods?.upi?.apps || []}
          testMode={String(methods?.upi?.checkout_key || '').startsWith('rzp_test_')}
          mode={mode}
          onMode={(value) => { setMode(value); setFailure(null); }}
          upiApp={upiApp}
          onUpiApp={setUpiApp}
          onPay={onPay}
          busy={false}
          disabled={!methods}
          error={UPI.includes(mode) && chosen?.provider === 'RAZORPAY' ? razorpay.error : ''}
          payLabel={failure && outcomeUnknown(failure) ? 'Try again safely' : undefined}
        />

        {simulated && (
          <p className="mt-2 text-center text-2xs text-amber-700">
            Development build - this payment runs against a simulated gateway.
          </p>
        )}

        <Sheet
          open={sandboxOpen}
          onClose={() => setSandboxOpen(false)}
          title="Simulated gateway"
        >
          <p className="mb-4 rounded-xl bg-amber-50 px-3.5 py-3 text-xs leading-relaxed text-amber-800">
            Development only. No real money moves. Choose what the bank should do
            with this {money(payable)} payment.
          </p>
          <div className="space-y-2 pb-2">
            {SANDBOX_OUTCOMES.map((outcome) => (
              <button
                key={outcome.value}
                type="button"
                onClick={() => pay(outcome.value)}
                className={cx(
                  'flex w-full items-center justify-between gap-3 rounded-2xl border p-3.5 text-left transition active:scale-[0.99]',
                  outcome.tone === 'mint'
                    ? 'border-mint bg-mint-50 hover:bg-mint-100'
                    : 'border-line hover:border-ink/20 hover:bg-mist/50',
                )}
              >
                <span>
                  <span className="block text-sm font-semibold text-ink">{outcome.label}</span>
                  <span className="block text-2xs text-slate">{outcome.hint}</span>
                </span>
                <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate" fill="none" aria-hidden="true">
                  <path d="M7 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ))}
          </div>
        </Sheet>
      </div>
    );
  }

  /* ── Amount ─────────────────────────────────────────────────────────── */
  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader
        title="Pay your bill"
        subtitle={statement?.due_date && statement.amount_outstanding > 0 ? `Statement due ${date(statement.due_date)}` : null}
        back="/credit"
      />

      <Card className="mb-4 overflow-hidden !p-0">
        <div className="bg-gradient-to-br from-ink via-[#0f1a1f] to-[#062019] px-5 py-6 text-center text-white">
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-white/60">
            Total outstanding
          </p>
          <p className="money mt-1 text-4xl font-bold tracking-tight">{money(outstanding)}</p>
          {minimum > 0 && (
            <p className="mt-2 text-xs text-white/70">
              Minimum due <span className="money font-semibold text-white">{money(minimum)}</span>
              {statement?.status === 'OVERDUE' && (
                <span className="ml-1 font-semibold text-red-300">· overdue</span>
              )}
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 divide-x divide-line text-center">
          <div className="p-3">
            <p className="text-2xs uppercase tracking-wider text-slate">Available now</p>
            <p className="money mt-0.5 text-sm font-semibold text-ink">{money(account?.available_credit)}</p>
          </div>
          <div className="p-3">
            <p className="text-2xs uppercase tracking-wider text-slate">Credit limit</p>
            <p className="money mt-0.5 text-sm font-semibold text-ink">{money(account?.credit_limit)}</p>
          </div>
        </div>
      </Card>

      <Card className="space-y-5 p-5 sm:p-6">
        {presets.length > 0 && (
          <div className="grid gap-2.5 sm:grid-cols-2">
            {presets.map((preset) => {
              const active = payable === preset.value;
              return (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => { setAmount(String(preset.value)); setError(''); }}
                  aria-pressed={active}
                  className={cx(
                    'rounded-2xl border p-3.5 text-left transition-all duration-base active:scale-[0.98]',
                    active ? 'border-mint bg-mint-50 ring-2 ring-mint/25' : 'border-line bg-canvas hover:border-ink/20',
                  )}
                >
                  <span className="block text-sm font-medium text-ink">{preset.label}</span>
                  <span className="money mt-0.5 block text-lg font-bold text-ink">{money(preset.value)}</span>
                  {preset.hint && <span className="mt-0.5 block text-2xs text-slate">{preset.hint}</span>}
                </button>
              );
            })}
          </div>
        )}

        <Input
          label="Amount to pay"
          prefix="₹"
          inputMode="decimal"
          placeholder="0"
          value={amount}
          onChange={(event) => { setAmount(sanitizeAmount(event.target.value)); setError(''); }}
          error={error}
          hint={`Anything from ${money(minimumAmount)} up to ${money(outstanding)}.`}
        />

        <Button variant="mint" size="lg" full onClick={toMethodStep}>
          {payable > 0 ? `Continue to pay ${money(payable)}` : 'Continue'}
        </Button>

        <p className="text-center text-2xs leading-relaxed text-slate">
          Your credit is restored as soon as your bank confirms the payment.
        </p>
      </Card>
    </div>
  );
}
