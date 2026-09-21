import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, Spinner, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { PaymentMethodPicker, PaymentProgress } from '../../components/payments/PaymentMethods';
import { useFetch } from '../../hooks/useProfile';
import { useRazorpay } from '../../hooks/useRazorpay';
import { date, money, sanitizeAmount } from '../../utils/format';

/**
 * Pay an EMI installment (PRD FR-008).
 *
 * UPI runs through Razorpay Checkout. The shape of this screen follows from one
 * rule: **the browser never decides that a payment succeeded.** Checkout's
 * success handler is treated as "something happened, go ask the server", and
 * the server verifies the signature and re-reads the payment from Razorpay
 * before an EMI moves. Every branch below - success, dismissal, failure,
 * timeout, refresh - ends in a server call, never in a local assumption.
 *
 * The permitted-instrument list comes from the server, and so does the reason a
 * credit card is missing. Explaining the prohibition beats silently omitting
 * the option a user is looking for.
 */

const UPI_MODES = ['UPI_INTENT', 'UPI_COLLECT'];
const SETTLED = ['SETTLED', 'SUCCESSFUL'];

/* How long to keep asking the server about a PENDING payment before handing the
   user a manual button. A UPI collect can legitimately take a couple of
   minutes; past that, polling on a mounted screen is just burning battery. */
const POLL_INTERVAL_MS = 5000;
const POLL_CEILING_MS = 150000;

export default function EmiPay() {
  const { emiId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const razorpay = useRazorpay();

  const { data: emi, loading } = useFetch(() => endpoints.emi.get(emiId), [emiId]);
  const { data: methods } = useFetch(() => endpoints.emiPayments.methods(), []);

  const [mode, setMode] = useState('UPI_INTENT');
  const [upiApp, setUpiApp] = useState('google_pay');
  const [amount, setAmount] = useState('');
  const [stage, setStage] = useState('form');
  const [payment, setPayment] = useState(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);

  /* Guards a double-tap on Pay. `busy` is state and therefore one render
     behind; a ref is not, and two clicks 50ms apart both read the stale
     `false` otherwise. The server's in-flight check is the real defence, but
     this stops the request ever being made twice. */
  const inFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);

  const isUpi = UPI_MODES.includes(mode);
  const payable = amount ? Number(amount) : Number(emi?.emi_amount || 0);
  const upiConfig = methods?.upi;

  /* ── Server-side resolution ───────────────────────────────────────── */

  /**
   * Take whatever Checkout returned to the server and let it decide.
   *
   * Called for success, for failure and for a dismissal that turned out to
   * have paid. The result of this call - not the browser's - is what the user
   * is shown.
   */
  const resolve = useCallback(async (paymentId, handlerPayload) => {
    setStage('verifying');
    try {
      const response = handlerPayload
        ? await endpoints.emiPayments.verify(paymentId, handlerPayload)
        : await endpoints.emiPayments.confirm(paymentId);

      if (!mounted.current) return null;
      setPayment(response.data);
      setStage('done');

      if (SETTLED.includes(response.data.status)) toast.success('EMI paid successfully.');
      return response.data;
    } catch (err) {
      if (!mounted.current) return null;
      // Verification itself failed - a network drop on the way back, most
      // likely. The payment may well have succeeded, so this is explicitly not
      // reported as a failed payment; the poller below picks it up.
      toast.error(err.message);
      setStage('done');
      setPayment((current) => current || { payment_id: paymentId, status: 'PENDING' });
      return null;
    }
  }, [toast]);

  /**
   * Poll a PENDING payment.
   *
   * This is the net under every interruption: a closed tab, a dropped network,
   * a webhook that lands before the browser gets back. The server is the only
   * thing that knows, so the screen just keeps asking it.
   */
  useEffect(() => {
    if (stage !== 'done' || !payment?.payment_id) return undefined;
    if (payment.is_terminal || SETTLED.includes(payment.status)) return undefined;
    if (payment.status !== 'PENDING') return undefined;

    setPolling(true);
    const startedAt = Date.now();

    const timer = setInterval(async () => {
      if (Date.now() - startedAt > POLL_CEILING_MS) {
        clearInterval(timer);
        if (mounted.current) setPolling(false);
        return;
      }

      try {
        const response = await endpoints.emiPayments.get(payment.payment_id);
        if (!mounted.current) return;

        if (response.data.status !== payment.status) {
          setPayment(response.data);
          if (SETTLED.includes(response.data.status)) {
            clearInterval(timer);
            setPolling(false);
            toast.success('EMI paid successfully.');
          }
        }
      } catch {
        /* Keep polling. A single failed check is not an answer. */
      }
    }, POLL_INTERVAL_MS);

    return () => {
      clearInterval(timer);
      setPolling(false);
    };
  }, [stage, payment?.payment_id, payment?.status, payment?.is_terminal, toast]);

  /* ── Pay ──────────────────────────────────────────────────────────── */

  async function pay() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);

    let opened = null;

    try {
      const response = await endpoints.emiPayments.pay({
        emi_id: emiId,
        amount: amount ? Number(amount) : undefined,
        payment_mode: mode,
        upi_app: isUpi ? upiApp : undefined,
      });

      opened = response.data;
      setPayment(opened);

      const checkout = opened.checkout || {};

      // Sandbox rail, or a non-UPI instrument: there is no Checkout to open,
      // so the server resolves it directly exactly as it always has.
      if (checkout.provider !== 'RAZORPAY' || !checkout.key) {
        await resolve(opened.payment_id, null);
        return;
      }

      setStage('awaiting');

      let result;
      try {
        result = await razorpay.open({
          key: checkout.key,
          order_id: checkout.order_id,
          // Amount and currency come from the server's order, never from this
          // screen. A browser that could choose the amount could pay one rupee
          // against a thirty-thousand-rupee installment.
          amount: checkout.amount_paise,
          currency: checkout.currency || 'INR',
          name: 'CashU',
          description: `${emi.provider_name} EMI`,
          prefill: {
            ...(checkout.prefill || {}),
            ...(isUpi ? { method: 'upi' } : {}),
          },
          notes: { emi_id: emiId, payment_id: opened.payment_id },
          theme: { color: '#00F5B8' },
        });
      } catch (openError) {
        // Checkout never opened - a blocked script, or no network. Nothing was
        // charged, so cancel rather than confirm: leaving it PENDING would
        // block the retry behind a payment that never started.
        toast.error(openError.message);
        setStage('verifying');
        const aborted = await endpoints.emiPayments.cancel(opened.payment_id);
        if (!mounted.current) return;
        setPayment(aborted.data);
        setStage('done');
        return;
      }

      if (result.outcome === 'paid') {
        await resolve(opened.payment_id, {
          razorpay_payment_id: result.response.razorpay_payment_id,
          razorpay_order_id: result.response.razorpay_order_id,
          razorpay_signature: result.response.razorpay_signature,
        });
        return;
      }

      if (result.outcome === 'failed') {
        // Razorpay says the attempt failed. Confirm it with the server rather
        // than showing a failure the backend has not recorded.
        await resolve(opened.payment_id, null);
        return;
      }

      // Dismissed. They may still have paid and closed the sheet, so the
      // server checks the gateway before cancelling anything.
      setStage('verifying');
      const cancelled = await endpoints.emiPayments.cancel(opened.payment_id);
      if (!mounted.current) return;
      setPayment(cancelled.data);
      setStage('done');
    } catch (err) {
      if (!mounted.current) return;

      if (err.code === 'CONFLICT') {
        // An earlier attempt is still open. Sending them round again would
        // create the second order this guard exists to prevent.
        toast.error(err.message);
        setStage('form');
      } else if (opened?.payment_id) {
        // The order opened but something after it broke. Ask the server what
        // state it is actually in instead of guessing.
        await resolve(opened.payment_id, null);
      } else {
        toast.error(err.message);
        setStage('form');
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function retry() {
    setPayment(null);
    setStage('form');
  }

  async function checkAgain() {
    if (!payment?.payment_id) return;
    setBusy(true);
    try {
      const response = await endpoints.emiPayments.confirm(payment.payment_id);
      setPayment(response.data);
      if (SETTLED.includes(response.data.status)) toast.success('EMI paid successfully.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  /* ── Loading ─────────────────────────────────────────────────────── */
  if (loading) {
    return (
      <div>
        <PageHeader title="Pay EMI" back={`/emi/${emiId}`} />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-56 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  /* ── In flight ───────────────────────────────────────────────────── */
  if (stage === 'awaiting' || stage === 'verifying') {
    return <PaymentProgress stage={stage} />;
  }

  /* ── Payment method ──────────────────────────────────────────────── */
  if (stage === 'method') {
    return (
      <div>
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader
            title="Payment method"
            subtitle={emi.provider_name}
            back={() => setStage('form')}
          />
          <div className="px-4 pt-4">
            <PaymentMethodPicker
              amount={payable}
              caption={
                emi.next_due_date ? `Installment due ${date(emi.next_due_date)}` : null
              }
              methods={methods?.permitted || []}
              prohibited={methods?.prohibited || []}
              upiApps={upiConfig?.apps || []}
              mode={mode}
              onMode={setMode}
              upiApp={upiApp}
              onUpiApp={setUpiApp}
              onPay={pay}
              busy={busy}
              error={isUpi ? razorpay.error : ''}
            />
          </div>
        </div>
      </div>
    );
  }

  /* ── Outcome ─────────────────────────────────────────────────────── */
  if (stage === 'done' && payment) {
    const settled = SETTLED.includes(payment.status);
    const pending = payment.status === 'PENDING';
    const cancelled = payment.status === 'CANCELLED';

    return (
      <div>
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader title="" back={`/emi/${emiId}`} />

          <div className="px-6 pt-8 text-center">
            <div
              className={cx(
                'mx-auto grid h-20 w-20 animate-scale-in place-items-center rounded-full',
                settled && 'bg-mint text-ink',
                pending && 'bg-amber-50 text-warn',
                !settled && !pending && 'bg-red-50 text-alert',
              )}
            >
              {settled ? (
                <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none">
                  <path
                    d="M5 12.5l5 5 9-9"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : pending ? (
                <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                  <path d="M12 7v5.5l3.5 2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                  <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              )}
            </div>

            <h1 className="mt-5 text-2xl font-bold text-ink">
              {settled ? 'EMI paid' : pending ? 'Payment pending' : cancelled ? 'Payment cancelled' : 'Payment failed'}
            </h1>

            <p className="mx-auto mt-2 max-w-xs text-sm text-slate">
              {settled && `${money(payment.amount)} paid to ${emi.provider_name}.`}
              {pending && 'Your bank has not confirmed this yet. We will update it automatically — do not pay again.'}
              {cancelled && 'Nothing was charged. You can start a new payment whenever you are ready.'}
              {!settled && !pending && !cancelled &&
                (payment.failure_reason || 'The payment could not be completed. Nothing was charged.')}
            </p>

            {settled && (
              <p className="money mt-6 text-[2.25rem] font-bold text-ink">
                {money(payment.amount)}
              </p>
            )}

            {pending && polling && (
              <p className="mt-4 inline-flex items-center gap-2 text-2xs text-slate">
                <Spinner className="h-3 w-3" />
                Checking automatically…
              </p>
            )}
          </div>

          <div className="mt-8 px-5">
            <Card className="divide-y divide-line py-1">
              <Row label="Lender" value={emi.provider_name} />
              <Row label="Loan account" value={emi.masked_loan_account} mono />
              <Row label="Paid via" value={payment.payment_mode?.replace(/_/g, ' ')} />
              {payment.upi_rrn && <Row label="UPI reference" value={payment.upi_rrn} mono />}
              {payment.bbps_rrn && <Row label="Biller reference" value={payment.bbps_rrn} mono />}
              {payment.installment_number && (
                <Row label="Installment" value={`#${payment.installment_number}`} mono />
              )}
            </Card>
          </div>

          <div className="mt-6 space-y-2 px-5">
            {pending && (
              <Button variant="outline" size="lg" full loading={busy} onClick={checkAgain}>
                Check status now
              </Button>
            )}

            {(cancelled || (!settled && !pending)) && (
              <Button variant="mint" size="lg" full onClick={retry}>
                Try again
              </Button>
            )}

            <Button
              variant={settled ? 'mint' : 'ghost'}
              size="lg"
              full
              onClick={() => navigate(`/emi/${emiId}`)}
            >
              Back to EMI
            </Button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Form ────────────────────────────────────────────────────────── */
  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Pay EMI" subtitle={emi.provider_name} back={`/emi/${emiId}`} />

        <div className="space-y-4 px-4 pt-4">
          <section className="rounded-2xl border border-line bg-canvas p-5 text-center">
            <p className="text-2xs uppercase tracking-wider text-slate">Amount due</p>
            <p className="money mt-1.5 text-[2rem] font-bold text-ink">{money(payable)}</p>
            {emi.next_due_date && (
              <p className="mt-1 text-xs text-slate">Due {date(emi.next_due_date)}</p>
            )}
            {emi.tenure_remaining != null && emi.total_tenure != null && (
              <p className="mt-1 text-2xs text-slate">
                Installment #{emi.total_tenure - emi.tenure_remaining + 1} of {emi.total_tenure}
              </p>
            )}
          </section>

          <Input
            label="Amount"
            hint="Leave blank to pay the full installment."
            prefix="₹"
            inputMode="numeric"
            placeholder={String(emi.emi_amount)}
            value={amount}
            onChange={(event) => setAmount(sanitizeAmount(event.target.value))}
          />

          <Button
            variant="mint"
            size="lg"
            full
            disabled={payable <= 0}
            onClick={() => setStage('method')}
          >
            Continue
          </Button>
        </div>
      </div>
    </div>
  );
}
