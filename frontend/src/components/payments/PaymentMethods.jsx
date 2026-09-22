import { Button, Card, cx } from '../ui';
import { IconLock } from '../layout/AppShell';
import { money } from '../../utils/format';

/**
 * The payment-method step, shared by transfers and EMI payments.
 *
 * It exists as its own screen rather than a section of the amount form because
 * choosing how to pay is a decision, and decisions deserve their own step. It
 * also gives the flow a natural place to stop: the amount is settled and shown
 * back, and nothing has been charged yet.
 *
 * The method list always comes from the server. Which instruments are legal
 * differs by product - an EMI may not be paid from a credit line, a transfer
 * must be - and that is a rule the backend owns. This component renders what it
 * is told, including the reason an instrument is missing, because "why can't I
 * see UPI here?" is better answered than left to guesswork.
 */
export function PaymentMethodPicker({
  amount,
  caption,
  testMode,
  methods = [],
  prohibited = [],
  upiApps = [],
  mode,
  onMode,
  upiApp,
  onUpiApp,
  onPay,
  busy,
  disabled,
  error,
  payLabel,
}) {
  const upiSelected = mode && String(mode).startsWith('UPI');

  return (
    <div className="space-y-4">
      <Card className="p-5 text-center">
        <p className="text-2xs uppercase tracking-wider text-slate">You are paying</p>
        <p className="money mt-1.5 text-[2rem] font-bold text-ink">{money(amount)}</p>
        {caption && <p className="mt-1 text-xs text-slate">{caption}</p>}
      </Card>

      <div>
        <p className="mb-2 text-sm font-medium text-ink">Choose a payment method</p>

        <div className="space-y-2">
          {methods.map((method) => (
            <button
              key={method.mode}
              type="button"
              onClick={() => onMode(method.mode)}
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
                {method.description && (
                  <p className="truncate text-2xs text-slate">{method.description}</p>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* The UPI app grid appears only once UPI is the chosen method - showing
          Google Pay and PhonePe before that would imply they are alternatives
          to UPI rather than ways of paying through it. */}
      {upiSelected && upiApps.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-ink">Preferred UPI app</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {upiApps.map((app) => (
              <button
                key={app.id}
                type="button"
                onClick={() => onUpiApp(app.id)}
                className={cx(
                  'rounded-xl border px-3 py-3 text-center text-xs font-medium transition',
                  upiApp === app.id
                    ? 'border-mint bg-mint-50 text-ink ring-2 ring-mint/25'
                    : 'border-line text-slate hover:border-ink/20 hover:text-ink',
                )}
              >
                {app.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-2xs leading-relaxed text-slate">
            On a phone, your UPI app opens with the amount filled in. On a
            desktop you will get a QR code to scan.
          </p>
        </div>
      )}

      {/* Test mode. Stated here because the gateway's own test cards and ours
          are different sets, and finding that out at the checkout sheet - as
          an "international cards are not supported" refusal - is a poor way to
          learn it. */}
      {testMode && (
        <div className="overflow-hidden rounded-xl border border-amber-300 bg-amber-50">
          <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-100/70 px-3.5 py-2">
            <span className="grid h-4 w-4 shrink-0 place-items-center rounded bg-amber-500 text-white">
              <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="3">
                <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
              </svg>
            </span>
            <p className="text-2xs font-bold uppercase tracking-[0.14em] text-amber-900">
              Test mode — no real money moves
            </p>
          </div>

          <div className="space-y-1.5 px-3.5 py-3 text-2xs leading-relaxed text-amber-900/80">
            <p>
              <span className="font-semibold text-amber-900">UPI is the reliable path here.</span>{' '}
              The gateway&rsquo;s test mode simulates it end to end.
            </p>
            <p>
              Card payments at the gateway need <em>its</em> test card numbers,
              not CashU&rsquo;s — ours are refused there as international. A
              CashU test card added from the Cards screen skips the gateway
              entirely and simulates the whole flow locally.
            </p>
          </div>
        </div>
      )}

      {prohibited.map((item) => (
        <div
          key={item.mode}
          className="flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3"
        >
          <IconLock className="mt-0.5 h-4 w-4 shrink-0 text-slate" />
          <p className="text-xs leading-relaxed text-slate">
            <span className="font-medium text-ink">{item.label} is not available.</span>{' '}
            {item.reason}
          </p>
        </div>
      ))}

      {error && (
        <p className="rounded-xl bg-red-50 px-3.5 py-3 text-xs text-alert">{error}</p>
      )}

      <Button
        variant="mint"
        size="lg"
        full
        loading={busy}
        disabled={disabled || !mode}
        onClick={onPay}
      >
        {payLabel || `Pay ${money(amount)}`}
      </Button>

      <p className="pb-2 text-center text-2xs text-slate">
        You will be asked to confirm in your bank or UPI app. Nothing is charged
        until you do.
      </p>
    </div>
  );
}

/**
 * The in-flight screen: checkout is open, or the server is being asked what
 * happened. Deliberately offers nothing to click - every button here would be
 * a way to pay twice.
 */
export function PaymentProgress({ stage }) {
  return (
    <div className="grid min-h-[60vh] place-items-center px-6">
      <div className="flex flex-col items-center text-center">
        <span className="relative grid h-14 w-14 place-items-center">
          <span className="absolute inset-0 animate-pulse-ring rounded-full bg-mint/30" />
          <span className="relative h-3 w-3 rounded-full bg-mint" />
        </span>
        <p className="mt-5 text-sm font-medium text-ink">
          {stage === 'awaiting'
            ? 'Complete the payment in your app'
            : 'Confirming your payment'}
        </p>
        <p className="mt-1 max-w-xs text-xs text-slate">
          {stage === 'awaiting'
            ? 'Approve the request, then come back here. Do not pay twice.'
            : 'Checking with your bank. This takes a moment.'}
        </p>
      </div>
    </div>
  );
}

export default PaymentMethodPicker;
