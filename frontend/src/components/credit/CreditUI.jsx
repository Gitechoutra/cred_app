import { useNavigate } from 'react-router-dom';

import { Badge, Button, Card, Meter, cx } from '../ui';
import { money } from '../../utils/format';

/**
 * The credit line's shared vocabulary and building blocks.
 *
 * One status map, one balance display and one set of outcome screens, used by
 * every credit screen. A transaction that reads "Failed" on one screen and
 * "Declined" on another, or a balance shown as "used" here and "outstanding"
 * there, is how people stop trusting the numbers.
 */

/* ── Status ─────────────────────────────────────────────────────────────── */

const STATUS = {
  PROCESSING: { label: 'Processing', tone: 'warn' },
  PENDING: { label: 'Processing', tone: 'warn' },
  SUCCEEDED: { label: 'Successful', tone: 'good' },
  FAILED: { label: 'Failed', tone: 'alert' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral' },
  // A purchase moves to REVERSED only once fully refunded.
  REVERSED: { label: 'Refunded', tone: 'neutral' },
};

/** Label and tone for a transaction, including a partial refund. */
export function transactionStatus(txn) {
  if (!txn) return STATUS.PROCESSING;
  if (txn.status === 'SUCCEEDED' && Number(txn.refunded_amount) > 0) {
    return { label: 'Partly refunded', tone: 'neutral' };
  }
  return STATUS[txn.status] || { label: txn.status, tone: 'neutral' };
}

export function TransactionStatusBadge({ transaction, className }) {
  const { label, tone } = transactionStatus(transaction);
  return <Badge tone={tone} dot className={className}>{label}</Badge>;
}

export const CREDIT_TYPE_LABEL = {
  PURCHASE: 'Card payment',
  PAYMENT: 'Bill payment',
  REFUND: 'Refund',
  FEE: 'Fee',
};

/** Merchant categories, mirroring MerchantCategory on the server. */
export const MERCHANT_CATEGORIES = [
  { value: 'SHOPPING', label: 'Shopping' },
  { value: 'GROCERIES', label: 'Groceries' },
  { value: 'DINING', label: 'Dining' },
  { value: 'TRAVEL', label: 'Travel' },
  { value: 'FUEL', label: 'Fuel' },
  { value: 'UTILITIES', label: 'Bills & utilities' },
  { value: 'HEALTHCARE', label: 'Health' },
  { value: 'EDUCATION', label: 'Education' },
  { value: 'ENTERTAINMENT', label: 'Entertainment' },
  { value: 'OTHER', label: 'Other' },
];

export function categoryLabel(value) {
  return MERCHANT_CATEGORIES.find((c) => c.value === value)?.label || null;
}

/* ── Balances ───────────────────────────────────────────────────────────── */

/**
 * Limit, available and used, side by side.
 *
 * Every figure comes from the server. Nothing here adds or subtracts - a
 * balance computed in the browser is a second opinion that can disagree with
 * the first.
 */
export function CreditBalances({ account, className }) {
  if (!account) return null;

  const utilization = Number(account.utilization_percent || 0);
  const tone = utilization > 80 ? 'alert' : utilization > 50 ? 'warn' : 'good';

  const stats = [
    { label: 'Credit limit', value: account.credit_limit },
    { label: 'Available', value: account.available_credit, emphasis: true },
    { label: 'Used', value: account.current_outstanding },
  ];

  return (
    <Card className={cx('p-4 sm:p-5', className)}>
      <div className="grid grid-cols-3 gap-2 sm:gap-4">
        {stats.map((stat) => (
          <div key={stat.label} className="min-w-0">
            <p className="truncate text-2xs font-medium uppercase tracking-wider text-slate">
              {stat.label}
            </p>
            <p
              className={cx(
                'money mt-1 truncate font-bold tracking-tight',
                stat.emphasis ? 'text-base text-mint-700 sm:text-xl' : 'text-sm text-ink sm:text-lg',
              )}
              title={money(stat.value)}
            >
              {money(stat.value, { decimals: 0 })}
            </p>
          </div>
        ))}
      </div>
      <Meter value={utilization} tone={tone} className="mt-4" />
      <p className="mt-2 text-2xs text-slate">
        {utilization > 80
          ? 'You are close to your limit. Paying your bill frees it up again.'
          : `${utilization}% of your limit is in use.`}
      </p>
    </Card>
  );
}

/* ── Outcome ────────────────────────────────────────────────────────────── */

const HERO = {
  success: {
    ring: 'bg-mint text-ink shadow-mint',
    halo: 'bg-mint/30',
    path: 'M6 12.5l4 4 8-9',
  },
  failure: {
    ring: 'bg-red-50 text-alert ring-1 ring-red-200',
    halo: 'bg-red-200/40',
    path: 'M8 8l8 8M16 8l-8 8',
  },
  cancelled: {
    ring: 'bg-mist text-slate ring-1 ring-line',
    halo: 'bg-slate-light/20',
    path: 'M7 12h10',
  },
  pending: {
    ring: 'bg-amber-50 text-warn ring-1 ring-amber-200',
    halo: 'bg-amber-200/50',
    path: 'M12 7v5.5l3.5 2',
  },
};

/**
 * The animated result of a money movement.
 *
 * The mark draws itself rather than appearing, and a pending result keeps a
 * slow pulse so it reads as "still happening" rather than as a frozen screen.
 * Reduced-motion users get the same states without the movement.
 */
export function StatusHero({ kind = 'success', title, subtitle, amount, amountTone }) {
  const style = HERO[kind] || HERO.success;

  return (
    <div className="flex flex-col items-center text-center">
      <span className="relative grid h-20 w-20 place-items-center">
        <span
          aria-hidden="true"
          className={cx(
            'absolute inset-0 rounded-full motion-safe:animate-pulse-ring',
            style.halo,
            kind !== 'pending' && '[animation-iteration-count:1]',
          )}
        />
        <span
          className={cx(
            'relative grid h-20 w-20 place-items-center rounded-full motion-safe:animate-pop',
            style.ring,
          )}
        >
          <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none" aria-hidden="true">
            {kind === 'pending' && (
              <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="2" />
            )}
            <path
              d={style.path}
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="draw-stroke"
            />
          </svg>
        </span>
      </span>

      {amount != null && (
        <p
          className={cx(
            'money mt-5 text-4xl font-bold tracking-tight motion-safe:animate-fade-up',
            amountTone || 'text-ink',
          )}
        >
          {amount}
        </p>
      )}
      <h2 className="mt-3 text-xl font-bold tracking-tight text-ink">{title}</h2>
      {subtitle && (
        <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-slate">
          {subtitle}
        </p>
      )}
    </div>
  );
}

/**
 * Full-area processing state for an in-flight payment. Offers nothing to
 * click on purpose: every button here would be a way to pay twice.
 */
export function ProcessingPanel({ title, subtitle }) {
  return (
    <div className="grid min-h-[50vh] place-items-center px-4" role="status" aria-live="polite">
      <div className="flex flex-col items-center text-center">
        <span className="relative grid h-16 w-16 place-items-center">
          <span className="absolute inset-0 rounded-full bg-mint/25 motion-safe:animate-pulse-ring" />
          <span className="absolute inset-2 rounded-full border-2 border-mint/30 border-t-mint-600 motion-safe:animate-spin" />
          <span className="relative h-3 w-3 rounded-full bg-mint-600" />
        </span>
        <p className="mt-6 text-base font-semibold text-ink">{title}</p>
        {subtitle && (
          <p className="mt-1.5 max-w-xs text-sm leading-relaxed text-slate">{subtitle}</p>
        )}
      </div>
    </div>
  );
}

/* ── Errors ─────────────────────────────────────────────────────────────── */

/**
 * What to tell somebody when a credit request fails.
 *
 * The server's message is used whenever it has one - it knows the amount, the
 * limit and the reason. This only fills in for failures that never reached the
 * server, or came back without a sentence a person could act on.
 */
export function friendlyError(error, fallback = 'Something went wrong. Please try again.') {
  if (!error) return fallback;
  if (error.code === 'NETWORK_ERROR') {
    return 'You appear to be offline. Check your connection - nothing has been charged twice.';
  }
  if (error.status >= 500 && !error.message) {
    return 'Our servers had a problem. Please try again in a moment.';
  }
  return error.message || fallback;
}

/** Whether a failure left the outcome unknown, so the same attempt should be retried. */
export function outcomeUnknown(error) {
  return error?.code === 'NETWORK_ERROR' || (error?.status >= 500 && error?.status !== 502 && error?.status !== 504);
}

/**
 * A failure as a card with a way forward. Never a blank screen: every error
 * state says what happened and offers the next step.
 */
export function ErrorCard({ error, title = 'We could not load this', onRetry, className }) {
  const navigate = useNavigate();
  const kyc = error?.code === 'KYC_REQUIRED';

  return (
    <Card className={cx('text-center', className)}>
      <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-red-50 text-alert">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
          <path d="M12 7.5v5M12 16h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </span>
      <p className="mt-3 text-base font-semibold text-ink">
        {kyc ? 'Verify your identity first' : title}
      </p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-slate">{friendlyError(error)}</p>
      {error?.recovery && !kyc && (
        <p className="mt-1 text-xs text-slate">{error.recovery}</p>
      )}
      <div className="mt-5 flex flex-col justify-center gap-2 sm:flex-row">
        {kyc && (
          <Button variant="mint" size="md" onClick={() => navigate('/kyc')}>
            Complete KYC
          </Button>
        )}
        {onRetry && (
          <Button variant={kyc ? 'outline' : 'mint'} size="md" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </Card>
  );
}

/* ── Journey ────────────────────────────────────────────────────────────── */

export const JOURNEY = [
  { key: 'APPLY', label: 'Apply' },
  { key: 'KYC', label: 'KYC' },
  { key: 'REVIEW', label: 'Review' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'PURPOSE', label: 'Purpose' },
  { key: 'ACTIVE', label: 'Active' },
];

/**
 * Where the holder is in the journey to a usable card.
 *
 * Scrolls inside itself on the narrowest phones rather than squeezing the
 * labels or pushing the page sideways.
 */
export function JourneySteps({ current, failed = false, className }) {
  const at = Math.max(0, JOURNEY.findIndex((s) => s.key === current));

  return (
    <nav aria-label="Credit card progress" className={cx('-mx-1 overflow-x-auto px-1', className)}>
      <ol className="flex min-w-max items-center gap-1.5 sm:min-w-0">
        {JOURNEY.map((step, index) => {
          const done = index < at;
          const here = index === at;
          return (
            <li key={step.key} className="flex items-center gap-1.5 sm:flex-1">
              <span
                className={cx(
                  'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs font-semibold transition-colors',
                  done && 'border-mint-200 bg-mint-50 text-mint-800',
                  here && !failed && 'border-ink bg-ink text-white',
                  here && failed && 'border-red-200 bg-red-50 text-alert',
                  !done && !here && 'border-line bg-canvas text-slate-light',
                )}
                aria-current={here ? 'step' : undefined}
              >
                {done ? (
                  <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" aria-hidden="true">
                    <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  <span className="money">{index + 1}</span>
                )}
                {step.label}
              </span>
              {index < JOURNEY.length - 1 && (
                <span
                  aria-hidden="true"
                  className={cx('hidden h-px flex-1 sm:block', done ? 'bg-mint-300' : 'bg-line')}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/* ── Quick actions ──────────────────────────────────────────────────────── */

export function ActionTile({ icon, label, hint, onClick, disabled, primary }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cx(
        'group flex min-w-0 flex-col items-start gap-3 rounded-2xl border p-3.5 text-left sm:p-4',
        'transition-all duration-base ease-glide active:scale-[0.98]',
        'disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
        primary
          ? 'border-mint-300/60 bg-gradient-to-br from-mint-50 to-canvas shadow-card hover:shadow-lift'
          : 'border-line bg-canvas shadow-card hover:-translate-y-0.5 hover:shadow-lift',
      )}
    >
      <span
        className={cx(
          'grid h-10 w-10 place-items-center rounded-xl transition-transform duration-base group-hover:scale-105',
          primary ? 'bg-mint text-ink' : 'bg-mist text-ink',
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-ink">{label}</span>
        {hint && <span className="mt-0.5 block truncate text-2xs text-slate">{hint}</span>}
      </span>
    </button>
  );
}

export function Glyph({ d, className = 'h-5 w-5' }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export const GLYPHS = {
  spend: 'M3 7.5A2.5 2.5 0 015.5 5h13A2.5 2.5 0 0121 7.5v9a2.5 2.5 0 01-2.5 2.5h-13A2.5 2.5 0 013 16.5v-9zM3 10h18M7 15h3',
  bill: 'M6 3h12v18l-3-2-3 2-3-2-3 2V3zm3 5h6m-6 4h6',
  statement: 'M7 3h7l5 5v13H7V3zm7 0v5h5M10 13h6M10 17h6',
  activity: 'M4 19V9m6 10V5m6 14v-7m4 7H2',
  freeze: 'M12 2v20M4.9 6.5l14.2 11M19.1 6.5L4.9 17.5',
};
