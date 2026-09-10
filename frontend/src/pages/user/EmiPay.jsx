import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader, IconLock } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, Spinner, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Pay an EMI installment (PRD FR-008).
 *
 * The permitted-instrument list comes from the server, and so does the reason a
 * credit card is missing. Explaining the prohibition beats silently omitting
 * the option a user is looking for.
 */
export default function EmiPay() {
  const { emiId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: emi, loading } = useFetch(() => endpoints.emi.get(emiId), [emiId]);
  const { data: methods } = useFetch(() => endpoints.emiPayments.methods(), []);

  const [mode, setMode] = useState('UPI_INTENT');
  const [amount, setAmount] = useState('');
  const [stage, setStage] = useState('form');
  const [payment, setPayment] = useState(null);
  const [busy, setBusy] = useState(false);

  const payable = amount ? Number(amount) : Number(emi?.emi_amount || 0);

  async function pay() {
    if (busy) return;
    setBusy(true);

    try {
      const response = await endpoints.emiPayments.pay({
        emi_id: emiId,
        amount: amount ? Number(amount) : undefined,
        payment_mode: mode,
      });

      setPayment(response.data);
      setStage('confirming');

      // Sandbox settles synchronously. With live credentials the user is handed
      // to their bank or UPI app here and returns to this screen afterwards.
      const confirmation = await endpoints.emiPayments.confirm(response.data.payment_id);
      setPayment(confirmation.data);
      setStage('done');

      if (['SETTLED', 'SUCCESSFUL'].includes(confirmation.data.status)) {
        toast.success('EMI paid successfully.');
      }
    } catch (err) {
      toast.error(err.message, {
        action: err.code === 'INSTRUMENT_NOT_PERMITTED' ? undefined : undefined,
      });
      setStage('form');
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="">
        <PageHeader title="Pay EMI" back={`/emi/${emiId}`} />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-56 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  /* ── Processing ──────────────────────────────────────────────────── */
  if (stage === 'confirming') {
    return (
      <div className="grid min-h-screen place-items-center bg-canvas px-6">
        <div className="flex flex-col items-center text-center">
          <Spinner className="h-8 w-8 text-mint-600" />
          <p className="mt-4 text-sm font-medium text-ink">Processing your payment</p>
          <p className="mt-1 text-xs text-slate">Please do not close this screen.</p>
        </div>
      </div>
    );
  }

  /* ── Outcome ─────────────────────────────────────────────────────── */
  if (stage === 'done' && payment) {
    const settled = ['SETTLED', 'SUCCESSFUL'].includes(payment.status);

    return (
      <div className="">
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader title="" back={`/emi/${emiId}`} />

          <div className="px-6 pt-8 text-center">
            <div
              className={cx(
                'mx-auto grid h-20 w-20 place-items-center rounded-full animate-scale-in',
                settled ? 'bg-mint text-ink' : 'bg-amber-50 text-warn',
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
              ) : (
                <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                  <path d="M12 7v5.5l3.5 2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              )}
            </div>

            <h1 className="mt-5 text-2xl font-bold text-ink">
              {settled ? 'EMI paid' : 'Payment pending'}
            </h1>
            <p className="mx-auto mt-2 max-w-xs text-sm text-slate">
              {settled
                ? `${money(payment.amount)} paid to ${emi.provider_name}.`
                : 'Your bank has not confirmed this yet. We will update you shortly and will not charge you twice.'}
            </p>

            {settled && (
              <p className="money mt-6 text-[2.25rem] font-bold text-ink">
                {money(payment.amount)}
              </p>
            )}
          </div>

          <div className="mt-8 px-5">
            <Card className="divide-y divide-line py-1">
              <Row label="Lender" value={emi.provider_name} />
              <Row label="Loan account" value={emi.masked_loan_account} mono />
              <Row label="Paid via" value={payment.payment_mode.replace(/_/g, ' ')} />
              {payment.bbps_rrn && <Row label="Reference" value={payment.bbps_rrn} mono />}
              {payment.installment_number && (
                <Row label="Installment" value={`#${payment.installment_number}`} mono />
              )}
            </Card>
          </div>

          <div className="mt-6 space-y-2 px-5">
            <Button variant="mint" size="lg" full onClick={() => navigate(`/emi/${emiId}`)}>
              Back to EMI
            </Button>
            <Button variant="ghost" size="lg" full onClick={() => navigate('/home')}>
              Go home
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
            <p className="money mt-1.5 text-[2rem] font-bold text-ink">
              {money(payable)}
            </p>
            {emi.next_due_date && (
              <p className="mt-1 text-xs text-slate">Due {date(emi.next_due_date)}</p>
            )}
          </section>

          <Input
            label="Amount"
            hint="Leave blank to pay the full installment."
            prefix="₹"
            inputMode="numeric"
            placeholder={String(emi.emi_amount)}
            value={amount}
            onChange={(event) => setAmount(event.target.value.replace(/\D/g, ''))}
          />

          <div>
            <p className="mb-2 text-sm font-medium text-ink">Pay using</p>

            <div className="space-y-2">
              {(methods?.permitted || []).map((method) => (
                <button
                  key={method.mode}
                  type="button"
                  onClick={() => setMode(method.mode)}
                  className={cx(
                    'flex w-full items-center gap-3 rounded-2xl border p-3.5 text-left transition',
                    mode === method.mode
                      ? 'border-mint bg-mint-50 ring-2 ring-mint/25'
                      : 'border-line hover:border-ink/20',
                  )}
                >
                  <span
                    className={cx(
                      'grid h-5 w-5 shrink-0 place-items-center rounded-full border-2',
                      mode === method.mode ? 'border-mint bg-mint' : 'border-line',
                    )}
                  >
                    {mode === method.mode && <span className="h-2 w-2 rounded-full bg-ink" />}
                  </span>

                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{method.label}</p>
                    <p className="truncate text-2xs text-slate">{method.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* The prohibition, stated rather than hidden (PRD 11.1). */}
          {methods?.prohibited?.map((item) => (
            <div key={item.mode} className="flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3">
              <IconLock className="mt-0.5 h-4 w-4 shrink-0 text-slate" />
              <p className="text-xs leading-relaxed text-slate">
                <span className="font-medium text-ink">{item.label} is not available.</span>{' '}
                {item.reason}
              </p>
            </div>
          ))}

          <Button variant="mint" size="lg" full loading={busy} onClick={pay}>
            Pay {money(payable)}
          </Button>
        </div>
      </div>
    </div>
  );
}
