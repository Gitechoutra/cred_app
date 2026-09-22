import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Spinner, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useQrScanner } from '../../hooks/useQrScanner';
import { useRazorpay } from '../../hooks/useRazorpay';
import { money, sanitizeAmount } from '../../utils/format';

/**
 * Scan and pay.
 *
 * Stages: scan -> confirm -> paying -> done.
 *
 * The scanned string is never parsed here. It goes to the server, which
 * validates the scheme, the address, the amount bounds and the display name,
 * and returns a structured summary. A QR is printed by anyone and read by a
 * camera; treating it as untrusted input is the whole security posture, and
 * doing that in the component would put it somewhere a modified client can
 * skip.
 */
export default function ScanPay() {
  const navigate = useNavigate();
  const toast = useToast();
  const razorpay = useRazorpay();

  const [stage, setStage] = useState('scan');
  const [payload, setPayload] = useState('');
  const [details, setDetails] = useState(null);
  const [amount, setAmount] = useState('');
  const [payment, setPayment] = useState(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualVpa, setManualVpa] = useState('');

  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const decode = useCallback(async (raw) => {
    setBusy(true);
    try {
      const response = await endpoints.qrPayments.decode(raw);
      if (!mounted.current) return;
      setPayload(raw);
      setDetails(response.data);
      setAmount(response.data.amount ? String(response.data.amount) : '');
      setStage('confirm');
    } catch (err) {
      if (!mounted.current) return;
      toast.error(err.message);
      scanner.start();
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [toast]); // eslint-disable-line react-hooks/exhaustive-deps

  const scanner = useQrScanner({ onDetect: decode });

  useEffect(() => {
    scanner.start();
    return scanner.stop;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const payable = Number(amount || 0);
  const canPay = details && payable > 0;

  async function pay() {
    if (inFlight.current || !canPay) return;
    inFlight.current = true;
    setBusy(true);

    let opened = null;

    try {
      const response = await endpoints.qrPayments.pay({
        payload,
        amount: details.amount_locked ? undefined : payable,
      });

      opened = response.data;
      setPayment(opened);

      const checkout = opened.checkout || {};

      // No gateway checkout on the simulated rail - the server resolves it.
      if (checkout.provider !== 'RAZORPAY' || !checkout.key) {
        const verified = await endpoints.qrPayments.verify(opened.qr_payment_id, {});
        if (!mounted.current) return;
        setPayment(verified.data);
        setStage('done');
        return;
      }

      setStage('paying');

      let result;
      try {
        result = await razorpay.open({
          key: checkout.key,
          order_id: checkout.order_id,
          amount: checkout.amount_paise,
          currency: checkout.currency || 'INR',
          name: 'CashU',
          description: `Payment to ${details.payee_name}`,
          prefill: { ...(checkout.prefill || {}), method: 'upi' },
          notes: { qr_payment_id: opened.qr_payment_id },
          theme: { color: '#00F5B8' },
        });
      } catch (openError) {
        toast.error(openError.message);
        const aborted = await endpoints.qrPayments.cancel(opened.qr_payment_id);
        if (!mounted.current) return;
        setPayment(aborted.data);
        setStage('done');
        return;
      }

      if (result.outcome === 'dismissed') {
        const aborted = await endpoints.qrPayments.cancel(opened.qr_payment_id);
        if (!mounted.current) return;
        setPayment(aborted.data);
        setStage('done');
        return;
      }

      const handler = result.outcome === 'paid' ? {
        razorpay_payment_id: result.response.razorpay_payment_id,
        razorpay_order_id: result.response.razorpay_order_id,
        razorpay_signature: result.response.razorpay_signature,
      } : {};

      const verified = await endpoints.qrPayments.verify(
        opened.qr_payment_id, handler,
      );
      if (!mounted.current) return;
      setPayment(verified.data);
      setStage('done');
    } catch (err) {
      if (!mounted.current) return;
      if (opened?.qr_payment_id) {
        const checked = await endpoints.qrPayments.get(opened.qr_payment_id);
        setPayment(checked.data);
        setStage('done');
      } else {
        toast.error(err.message);
        setStage('confirm');
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  /* ── Scanning ─────────────────────────────────────────────────────── */
  if (stage === 'scan') {
    return (
      <div>
        <div className="mx-auto w-full max-w-2xl">
          <PageHeader
            title="Scan & Pay"
            subtitle="Point your camera at any UPI QR code"
            back="/home"
          />

          <div className="px-4">
            <div className="relative aspect-square w-full overflow-hidden rounded-3xl bg-ink">
              <video
                ref={scanner.videoRef}
                playsInline
                muted
                className="h-full w-full object-cover"
              />

              {/* The frame. Four corners rather than a full box, so the view
                  stays open and the guide reads as a target. */}
              {scanner.state === 'scanning' && (
                <>
                  <span aria-hidden="true" className="pointer-events-none absolute inset-0 bg-ink/30" />
                  <div className="pointer-events-none absolute left-1/2 top-1/2 h-56 w-56 -translate-x-1/2 -translate-y-1/2 sm:h-64 sm:w-64">
                    <span className="absolute inset-0 rounded-2xl shadow-[0_0_0_9999px_rgba(10,15,13,0.45)]" />
                    {['left-0 top-0 border-l-2 border-t-2 rounded-tl-xl',
                      'right-0 top-0 border-r-2 border-t-2 rounded-tr-xl',
                      'left-0 bottom-0 border-b-2 border-l-2 rounded-bl-xl',
                      'right-0 bottom-0 border-b-2 border-r-2 rounded-br-xl',
                    ].map((corner) => (
                      <span
                        key={corner}
                        className={cx('absolute h-8 w-8 border-mint', corner)}
                      />
                    ))}

                    {/* The sweep. Pure transform, so it stays on the
                        compositor while the camera feed paints. */}
                    <span className="absolute inset-x-2 top-0 h-0.5 animate-scan-line rounded bg-mint shadow-mint" />
                  </div>
                </>
              )}

              {(scanner.state === 'starting' || busy) && (
                <div className="absolute inset-0 grid place-items-center bg-ink/60">
                  <div className="flex flex-col items-center">
                    <Spinner className="h-7 w-7 text-mint" />
                    <p className="mt-3 text-xs text-white/70">
                      {busy ? 'Reading the code' : 'Starting the camera'}
                    </p>
                  </div>
                </div>
              )}

              {scanner.state === 'error' && (
                <div className="absolute inset-0 grid place-items-center px-8">
                  <div className="text-center">
                    <p className="text-sm font-semibold text-white">
                      {scanner.error?.message}
                    </p>
                    {scanner.error?.code !== 'UNSUPPORTED' && (
                      <Button
                        variant="mint"
                        size="md"
                        className="mt-5"
                        onClick={scanner.start}
                      >
                        Try again
                      </Button>
                    )}
                  </div>
                </div>
              )}

              {scanner.torchAvailable && scanner.state === 'scanning' && (
                <button
                  type="button"
                  onClick={scanner.toggleTorch}
                  aria-label={scanner.torchOn ? 'Turn off the flashlight' : 'Turn on the flashlight'}
                  className={cx(
                    'absolute bottom-5 left-1/2 grid h-12 w-12 -translate-x-1/2',
                    'place-items-center rounded-full transition-all duration-base ease-glide',
                    scanner.torchOn
                      ? 'bg-mint text-ink shadow-mint'
                      : 'bg-white/15 text-white backdrop-blur hover:bg-white/25',
                  )}
                >
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="M9 2h6l-1 6h4l-8 14 2-9H7z" strokeLinejoin="round" />
                  </svg>
                </button>
              )}
            </div>

            <p className="mt-4 text-center text-xs text-slate">
              Align the QR code inside the frame.
            </p>

            {/* Manual entry: the fallback where the camera cannot be used at
                all, and a reasonable path for anyone who has the UPI ID. */}
            <div className="mt-6">
              {!manual ? (
                <button
                  type="button"
                  onClick={() => { scanner.stop(); setManual(true); }}
                  className="mx-auto block text-xs font-semibold text-mint-700 underline-offset-2 hover:underline"
                >
                  Enter a UPI ID instead
                </button>
              ) : (
                <Card className="p-4">
                  <Input
                    label="UPI ID"
                    placeholder="merchant@okaxis"
                    value={manualVpa}
                    autoCapitalize="none"
                    onChange={(event) => setManualVpa(event.target.value.trim())}
                  />
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="mint"
                      size="md"
                      full
                      loading={busy}
                      disabled={!manualVpa.includes('@')}
                      onClick={() => decode(`upi://pay?pa=${encodeURIComponent(manualVpa)}`)}
                    >
                      Continue
                    </Button>
                    <Button
                      variant="ghost"
                      size="md"
                      onClick={() => { setManual(false); scanner.start(); }}
                    >
                      Scan
                    </Button>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── In flight ────────────────────────────────────────────────────── */
  if (stage === 'paying') {
    return (
      <div className="grid min-h-[60vh] place-items-center px-6">
        <div className="flex flex-col items-center text-center">
          <span className="relative grid h-14 w-14 place-items-center">
            <span className="absolute inset-0 animate-pulse-ring rounded-full bg-mint/30" />
            <span className="relative h-3 w-3 rounded-full bg-mint" />
          </span>
          <p className="mt-5 text-sm font-medium text-ink">
            Complete the payment in your UPI app
          </p>
          <p className="mt-1 max-w-xs text-xs text-slate">
            Approve the request, then come back here. Do not pay twice.
          </p>
        </div>
      </div>
    );
  }

  /* ── Result ───────────────────────────────────────────────────────── */
  if (stage === 'done' && payment) {
    const ok = payment.status === 'SUCCESSFUL';
    const pending = payment.status === 'PENDING';
    const cancelled = payment.status === 'CANCELLED';

    return (
      <div>
        <div className="mx-auto w-full max-w-2xl">
          <PageHeader title="" back="/home" />

          <div className="px-6 pt-6 text-center">
            <div
              className={cx(
                'mx-auto grid h-20 w-20 animate-scale-in place-items-center rounded-full',
                ok && 'bg-mint text-ink',
                pending && 'bg-amber-50 text-warn',
                !ok && !pending && 'bg-red-50 text-alert',
              )}
            >
              {ok ? (
                <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none">
                  <path d="M5 12.5l5 5 9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
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
              {ok ? 'Payment successful' : pending ? 'Payment pending'
                : cancelled ? 'Payment cancelled' : 'Payment failed'}
            </h1>

            <p className="mx-auto mt-2 max-w-xs text-sm text-slate">
              {ok && `${money(payment.amount)} paid to ${payment.payee_name}.`}
              {pending && 'Your bank has not confirmed this yet. We will update it automatically — do not pay again.'}
              {cancelled && 'Nothing was charged.'}
              {!ok && !pending && !cancelled &&
                (payment.failure_reason || 'The payment could not be completed.')}
            </p>

            {ok && (
              <p className="money mt-6 text-[2.25rem] font-bold text-ink">
                {money(payment.amount)}
              </p>
            )}
          </div>

          <div className="mt-8 px-5">
            <Card className="divide-y divide-line py-1">
              <Row label="Paid to" value={payment.payee_name} />
              <Row label="UPI ID" value={payment.payee_vpa} mono />
              {payment.upi_rrn && <Row label="UPI reference" value={payment.upi_rrn} mono />}
              {payment.transaction_id && (
                <Row label="Transaction" value={payment.transaction_id.slice(0, 18)} mono />
              )}
            </Card>
          </div>

          <div className="mt-6 space-y-2 px-5">
            {!ok && !pending && (
              <Button variant="mint" size="lg" full onClick={() => {
                setPayment(null); setDetails(null); setStage('scan');
                setTimeout(scanner.start, 0);
              }}>
                Scan again
              </Button>
            )}
            <Button variant={ok ? 'mint' : 'ghost'} size="lg" full onClick={() => navigate('/transactions')}>
              View history
            </Button>
            <Button variant="ghost" size="lg" full onClick={() => navigate('/home')}>
              Done
            </Button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Confirm ──────────────────────────────────────────────────────── */
  return (
    <div>
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader
          title="Confirm payment"
          back={() => { setDetails(null); setStage('scan'); setTimeout(scanner.start, 0); }}
        />

        <div className="space-y-4 px-4 pt-4">
          <Card className="p-5 text-center">
            <p className="text-2xs uppercase tracking-wider text-slate">Paying</p>
            <p className="mt-1.5 text-lg font-bold text-ink">{details?.payee_name}</p>
            <p className="money mt-0.5 text-xs text-slate">{details?.payee_vpa}</p>
          </Card>

          {details?.amount_locked ? (
            <Card className="p-5 text-center">
              <p className="text-2xs uppercase tracking-wider text-slate">Amount</p>
              <p className="money mt-1.5 text-[2rem] font-bold text-ink">
                {money(details.amount)}
              </p>
              <p className="mt-1 text-2xs text-slate">
                Set by the merchant and cannot be changed.
              </p>
            </Card>
          ) : (
            <Input
              label="Amount"
              prefix="₹"
              inputMode="decimal"
              autoFocus
              placeholder="0"
              value={amount}
              onChange={(event) => setAmount(sanitizeAmount(event.target.value))}
              hint="Enter how much you want to pay."
            />
          )}

          {details?.note && (
            <div className="rounded-xl bg-mist px-3.5 py-3">
              <p className="text-2xs uppercase tracking-wider text-slate">Note</p>
              <p className="mt-1 text-sm text-ink">{details.note}</p>
            </div>
          )}

          <Row label="Payment method" value="UPI" />

          <Button
            variant="mint"
            size="lg"
            full
            loading={busy}
            disabled={!canPay}
            onClick={pay}
          >
            {canPay ? `Pay ${money(payable)}` : 'Enter an amount'}
          </Button>

          <p className="pb-2 text-center text-2xs text-slate">
            You will confirm this in your UPI app. Nothing is charged until you do.
          </p>
        </div>
      </div>
    </div>
  );
}
