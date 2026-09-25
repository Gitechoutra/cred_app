import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money, sanitizeAmount } from '../../utils/format';

/**
 * Pay the card bill.
 *
 * Three preset amounts, because those are the three decisions people actually
 * make: clear it, pay the minimum, or pay something in between. The minimum is
 * the server's number, not a percentage recomputed here - a minimum due that
 * disagrees with the statement by a rupee is worse than no shortcut at all.
 *
 * The amount is capped at what is outstanding, and the cap is enforced by the
 * server too. Overpaying would create a credit balance the product does not
 * model, so it is refused rather than banked.
 *
 * Success shows how much credit came back, because that is the thing the payer
 * came here for and the reason the product works the way it does.
 */

const METHODS = [
  { value: 'UPI', label: 'UPI', hint: 'Any UPI app' },
  { value: 'NETBANKING', label: 'Net banking', hint: '50+ banks' },
  { value: 'DEBIT_CARD', label: 'Debit card', hint: 'RuPay, Visa, Mastercard' },
];

export default function CreditPayBill() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: current, loading, refetch } = useFetch(
    () => endpoints.credit.currentStatement(), [],
  );

  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState('UPI');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  /* Guards a double tap. `busy` is state and therefore one render behind; two
     clicks 50ms apart both read the stale false. The server's idempotency key
     is the real defence - it answers a replay with the original payment - but
     this stops the request being made twice at all. */
  const inFlight = useRef(false);

  const account = current?.account;
  const statement = current?.latest_statement;
  const outstanding = Number(account?.current_outstanding || 0);
  const minimum = Number(statement?.minimum_outstanding || 0);

  const presets = [
    outstanding > 0 && {
      key: 'full',
      label: 'Pay in full',
      hint: 'Clears everything you owe',
      value: outstanding,
    },
    minimum > 0 && minimum < outstanding && {
      key: 'minimum',
      label: 'Minimum due',
      hint: statement?.due_date ? `By ${date(statement.due_date)}` : null,
      value: minimum,
    },
  ].filter(Boolean);

  function validate() {
    const value = Number(amount);
    if (!amount) return 'Enter an amount.';
    if (!Number.isFinite(value) || value <= 0) return 'Enter a valid amount.';
    if (value > outstanding) {
      return `You owe ${money(outstanding)}. Enter that or less.`;
    }
    return '';
  }

  async function pay() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    if (inFlight.current) return;

    inFlight.current = true;
    setBusy(true);
    setError('');

    try {
      const response = await endpoints.credit.payBill({
        amount,
        payment_method: method,
        statement_id: statement?.statement_id,
      });
      setDone(response.data);
    } catch (err) {
      setError(err?.message || 'We could not collect that payment.');
      // Re-read the balance: the refusal may be because it changed underneath
      // this screen, and the amount on display would then be wrong.
      refetch();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay your bill" back />
        <Card><Skeleton className="h-64 w-full" /></Card>
      </div>
    );
  }

  /* ── Paid ──────────────────────────────────────────────────────────── */
  if (done) {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Payment received" back="/credit" />

        <Card className="text-center">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-mint text-ink">
            <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" aria-hidden="true">
              <path
                d="M5 13l4 4L19 7"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>

          <p className="money mt-4 text-3xl font-bold text-ink">
            {money(done.transaction.amount)}
          </p>
          <p className="mt-1 text-sm text-slate">paid towards your card</p>

          <div className="mt-5 rounded-2xl border border-mint-600/30 bg-mint-50/50 p-4">
            <p className="text-2xs font-semibold uppercase tracking-wider text-mint-800">
              Credit restored
            </p>
            <p className="money mt-1 text-2xl font-bold text-ink">
              {money(done.credit_restored)}
            </p>
            <p className="mt-1 text-2xs text-slate">
              is available to spend again
            </p>
          </div>

          <div className="mt-5 text-left">
            <Row
              label="Still outstanding"
              value={money(done.account.current_outstanding)}
              mono
            />
            <Row
              label="Available credit"
              value={money(done.account.available_credit)}
              mono
            />
          </div>

          <div className="mt-5 space-y-2">
            <Button
              variant="mint"
              size="lg"
              full
              onClick={() => navigate('/credit', { replace: true })}
            >
              Back to my card
            </Button>
            <Button
              variant="ghost"
              size="lg"
              full
              onClick={() => navigate(
                `/credit/transactions/${done.transaction.credit_transaction_id}`,
              )}
            >
              View the receipt
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  /* ── Nothing to pay ───────────────────────────────────────────────── */
  if (outstanding <= 0) {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Pay your bill" back />
        <Card className="text-center">
          <Badge tone="good" dot>All clear</Badge>
          <p className="mt-3 text-base font-semibold text-ink">
            Nothing outstanding
          </p>
          <p className="mt-1 text-sm text-slate">
            Your full {money(account?.credit_limit)} limit is available.
          </p>
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-5"
            onClick={() => navigate('/credit', { replace: true })}
          >
            Back to my card
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader
        title="Pay your bill"
        subtitle={
          statement?.due_date ? `Due by ${date(statement.due_date)}` : null
        }
        back
      />

      <Card className="mb-4 text-center">
        <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
          Total outstanding
        </p>
        <p className="money mt-1 text-4xl font-bold text-ink">
          {money(outstanding)}
        </p>
        {minimum > 0 && (
          <p className="mt-2 text-xs text-slate">
            Minimum due{' '}
            <span className="money font-medium text-ink">{money(minimum)}</span>
            {statement?.status === 'OVERDUE' && (
              <span className="ml-1 font-medium text-alert">- overdue</span>
            )}
          </p>
        )}
      </Card>

      <Card className="space-y-5">
        {presets.length > 0 && (
          <div className="grid gap-2.5 sm:grid-cols-2">
            {presets.map((preset) => {
              const active = Number(amount) === preset.value;
              return (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => {
                    setAmount(String(preset.value));
                    setError('');
                  }}
                  aria-pressed={active}
                  className={cx(
                    'rounded-xl border p-3.5 text-left transition active:scale-[0.98]',
                    active
                      ? 'border-mint bg-mint-50 shadow-mint'
                      : 'border-line bg-canvas hover:border-ink/20',
                  )}
                >
                  <span className="block text-sm font-medium text-ink">
                    {preset.label}
                  </span>
                  <span className="money mt-0.5 block text-base font-bold text-ink">
                    {money(preset.value)}
                  </span>
                  {preset.hint && (
                    <span className="mt-0.5 block text-2xs text-slate">
                      {preset.hint}
                    </span>
                  )}
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
          onChange={(event) => {
            setAmount(sanitizeAmount(event.target.value));
            setError('');
          }}
          error={error}
          hint={`Anything up to ${money(outstanding)}.`}
        />

        <fieldset>
          <legend className="mb-2 text-sm font-medium text-ink">
            Pay using
          </legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {METHODS.map((option) => {
              const active = method === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMethod(option.value)}
                  aria-pressed={active}
                  className={cx(
                    'rounded-xl border p-3 text-left transition active:scale-[0.98]',
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
          <p className="mt-2 text-2xs text-slate">
            A credit card cannot be used to pay a credit card bill.
          </p>
        </fieldset>

        <Button
          variant="mint"
          size="lg"
          full
          loading={busy}
          disabled={!amount}
          onClick={pay}
        >
          {amount ? `Pay ${money(Number(amount))}` : 'Enter an amount'}
        </Button>

        <p className="text-center text-2xs leading-relaxed text-slate">
          The credit you pay back becomes available to spend again straight away.
        </p>
      </Card>
    </div>
  );
}
