import { Badge, Meter, cx } from '../ui';
import { IconAlert, IconBank, IconCheck, IconChevron, IconClock } from '../layout/AppShell';
import {
  date as fmtDate,
  money,
  relativeDays,
  statusLabel,
  statusTone,
  transactionLabel,
} from '../../utils/format';

/* ── Card tile ──────────────────────────────────────────────────────────── */

/**
 * A linked credit card.
 *
 * Painted in the issuer's brand colour so the user recognises it the way they
 * recognise the physical card in their wallet - the fastest possible way to
 * pick the right one when four are on screen.
 */
export function CardTile({ card, onClick, compact = false }) {
  const colour = card.brand_color || '#0A0F0D';
  const utilization = card.utilization_percentage;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'group relative w-full overflow-hidden rounded-2xl p-4 text-left',
        // Lift and shadow on hover, settling back on press. The shine sweep is
        // the shared .shine treatment used on the landing page, so a card
        // behaves the same wherever it appears.
        'shine transition-all duration-base ease-glide',
        'hover:-translate-y-0.5 hover:shadow-lift active:translate-y-0 active:scale-[0.985]',
        compact ? 'min-h-[124px]' : 'min-h-[156px]',
      )}
      style={{ backgroundColor: colour }}
    >
      {/* A soft highlight keeps a flat brand colour from reading as a plain
          rectangle, without tipping into skeuomorphism. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -right-8 -top-12 h-40 w-40 rounded-full bg-white/10 blur-2xl"
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/25"
      />

      <div className="relative flex h-full flex-col justify-between">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">
              {card.nickname || card.issuer_bank}
            </p>
            <p className="mt-0.5 text-2xs uppercase tracking-wider text-white/60">
              {card.network}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {/* Amber, on the card face itself. A simulated card should be
                identifiable at a glance from anywhere it appears, not only on
                the screen where it was added. */}
            {card.is_test_card && (
              <span className="rounded-full bg-amber-400 px-2 py-0.5 text-2xs font-bold uppercase tracking-wide text-amber-950">
                Test
              </span>
            )}

            {card.status !== 'ACTIVE' && (
              <span className="rounded-full bg-white/15 px-2 py-0.5 text-2xs font-semibold text-white">
                {statusLabel(card.status)}
              </span>
            )}
          </div>
        </div>

        <div className="space-y-2.5">
          <p className="money text-base tracking-[0.18em] text-white/85">
            {card.masked_pan}
          </p>

          {card.card_limit ? (
            <div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-2xs text-white/60">Available</span>
                <span className="money text-sm font-semibold text-white">
                  {money(card.available_limit ?? card.card_limit)}
                </span>
              </div>

              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/20">
                <div
                  className="h-full rounded-full bg-mint transition-all duration-700"
                  style={{ width: `${Math.min(100, utilization || 0)}%` }}
                />
              </div>

              <div className="mt-1 flex items-center justify-between">
                <span className="text-2xs text-white/50">
                  {utilization !== null && utilization !== undefined
                    ? `${utilization}% used`
                    : 'Limit not tracked'}
                </span>
                {card.next_due_date && (
                  <span className="text-2xs text-white/50">
                    Due {relativeDays(card.next_due_date)}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <p className="text-2xs text-white/50">Tap to add your credit limit</p>
          )}
        </div>
      </div>
    </button>
  );
}

/* ── Due item ───────────────────────────────────────────────────────────── */

/**
 * A card bill or EMI that needs paying.
 *
 * Overdue is marked with a border and a label, never a red fill - this is a
 * debt app, and a wall of red reads as judgement rather than information.
 */
export function DueItem({ item, onClick }) {
  const overdue = item.is_overdue;
  const urgent = !overdue && item.days_remaining <= 3;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'flex w-full items-center gap-3 rounded-2xl border bg-canvas p-3.5 text-left',
        'transition-shadow hover:shadow-card active:scale-[0.99]',
        overdue ? 'border-alert/30' : 'border-line',
      )}
    >
      <span
        className={cx(
          'grid h-10 w-10 shrink-0 place-items-center rounded-xl',
          overdue ? 'bg-red-50 text-alert' : urgent ? 'bg-amber-50 text-warn' : 'bg-mist text-slate',
        )}
      >
        {overdue ? <IconAlert className="h-5 w-5" /> : <IconClock className="h-5 w-5" />}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-ink">{item.title}</p>
        <p className="truncate text-xs text-slate">{item.subtitle}</p>
      </div>

      <div className="shrink-0 text-right">
        <p className="money text-sm font-semibold text-ink">{money(item.amount)}</p>
        <p
          className={cx(
            'text-2xs font-medium',
            overdue ? 'text-alert' : urgent ? 'text-warn' : 'text-slate',
          )}
        >
          {overdue ? 'Overdue' : relativeDays(item.due_date)}
        </p>
      </div>

      {item.auto_pay && (
        <span className="shrink-0" title="Auto-pay is on">
          <IconCheck className="h-4 w-4 text-mint-600" />
        </span>
      )}
    </button>
  );
}

/* ── EMI row ────────────────────────────────────────────────────────────── */

export function EmiRow({ emi, onClick }) {
  const progress = emi.progress_percentage;

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-2xl border border-line bg-canvas p-3.5 text-left transition-shadow hover:shadow-card active:scale-[0.99]"
    >
      <span
        className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-2xs font-bold text-white"
        style={{ backgroundColor: emi.brand_color || '#0A0F0D' }}
      >
        {(emi.provider_name || '?').slice(0, 2).toUpperCase()}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold text-ink">
            {emi.nickname || emi.provider_name}
          </p>
          {emi.auto_pay_status === 'ACTIVE' && (
            <Badge tone="good" className="shrink-0">Auto</Badge>
          )}
        </div>

        <p className="truncate text-xs text-slate">{emi.masked_loan_account}</p>

        {progress !== null && progress !== undefined && (
          <div className="mt-2 flex items-center gap-2">
            <Meter value={progress} tone="good" className="flex-1" />
            <span className="money shrink-0 text-2xs text-slate">
              {emi.tenure_remaining}/{emi.total_tenure} left
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 text-right">
        <p className="money text-sm font-semibold text-ink">{money(emi.emi_amount)}</p>
        <p
          className={cx(
            'text-2xs font-medium',
            emi.payment_status === 'OVERDUE' ? 'text-alert' : 'text-slate',
          )}
        >
          {emi.payment_status === 'OVERDUE'
            ? 'Overdue'
            : emi.next_due_date
              ? relativeDays(emi.next_due_date)
              : 'Closed'}
        </p>
      </div>
    </button>
  );
}

/* ── Transaction row ────────────────────────────────────────────────────── */

export function TransactionRow({ transaction, onClick }) {
  const tone = statusTone(transaction.status);
  const credit = transaction.type === 'REVERSAL_REFUND';

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 px-1 py-3 text-left transition active:opacity-70"
    >
      <span
        className={cx(
          'grid h-10 w-10 shrink-0 place-items-center rounded-xl',
          tone === 'good' && 'bg-mint-50 text-mint-700',
          tone === 'warn' && 'bg-amber-50 text-warn',
          tone === 'alert' && 'bg-red-50 text-alert',
          tone === 'neutral' && 'bg-mist text-slate',
        )}
      >
        {tone === 'good' ? (
          <IconCheck className="h-5 w-5" />
        ) : tone === 'alert' ? (
          <IconAlert className="h-5 w-5" />
        ) : (
          <IconClock className="h-5 w-5" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">
          {transactionLabel(transaction.type)}
        </p>
        <p className="truncate text-xs text-slate">
          {transaction.destination || transaction.source}
        </p>
      </div>

      <div className="shrink-0 text-right">
        <p
          className={cx(
            'money text-sm font-semibold',
            credit ? 'text-mint-700' : 'text-ink',
          )}
        >
          {credit ? '+' : '−'}
          {money(transaction.gross_amount ?? transaction.amount, { symbol: true }).replace('₹', '₹')}
        </p>
        <p className="text-2xs text-slate">{fmtDate(transaction.created_on, { withYear: false })}</p>
      </div>
    </button>
  );
}

/* ── Bank account row ───────────────────────────────────────────────────── */

export function BankRow({ account, onClick, selected = false, selectable = false }) {
  const verified = account.is_payout_eligible;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'flex w-full items-center gap-3 rounded-2xl border bg-canvas p-3.5 text-left transition',
        selected ? 'border-mint ring-2 ring-mint/25' : 'border-line hover:shadow-card',
        !verified && selectable && 'opacity-60',
      )}
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mist text-slate">
        <IconBank className="h-5 w-5" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold text-ink">{account.bank_name}</p>
          {account.is_primary && <Badge tone="neutral" className="shrink-0">Primary</Badge>}
        </div>
        <p className="money truncate text-xs text-slate">{account.masked_account}</p>
      </div>

      {verified ? (
        <Badge tone="good" dot className="shrink-0">Verified</Badge>
      ) : (
        <Badge tone={statusTone(account.penny_drop_status)} className="shrink-0">
          {statusLabel(account.penny_drop_status)}
        </Badge>
      )}
    </button>
  );
}

/* ── Fee breakdown ──────────────────────────────────────────────────────── */

/**
 * Fee disclosure.
 *
 * PRD 9.2 makes this a non-skippable disclosure before the 3DS challenge: the
 * user must see exactly what is charged, and what of it is fee, before they
 * authorise anything. The two emphasised rows are the two numbers that
 * actually matter.
 */
export function FeeBreakdown({ quote, className }) {
  if (!quote?.breakdown) return null;

  return (
    <div className={cx('rounded-2xl border border-line bg-mist/60 p-4', className)}>
      {quote.breakdown.map((row, index) => {
        const isTotal = row.emphasis;
        const isLast = index === quote.breakdown.length - 1;

        return (
          <div
            key={row.label}
            className={cx(
              'flex items-baseline justify-between gap-4 py-1.5',
              isTotal && index > 0 && !isLast && 'mt-1.5 border-t border-line pt-3',
            )}
          >
            <span className={cx('text-sm', isTotal ? 'font-medium text-ink' : 'text-slate')}>
              {row.label}
            </span>
            <span
              className={cx(
                'money text-right',
                isTotal ? 'text-base font-bold text-ink' : 'text-sm text-ink',
                isLast && 'text-mint-700',
              )}
            >
              {money(row.amount)}
            </span>
          </div>
        );
      })}

      <p className="mt-3 border-t border-line pt-3 text-2xs leading-relaxed text-slate">
        GST is charged on fees only, never on the amount you pay. Fees are
        disclosed before you authorise the payment.
      </p>
    </div>
  );
}

/* ── Timeline ───────────────────────────────────────────────────────────── */

/**
 * Payment and application progress.
 *
 * A raw status string means nothing to someone whose money or application is in
 * flight, so the state machine is rendered as a sequence of things that have
 * happened.
 */
export function Timeline({ steps }) {
  if (!steps?.length) return null;

  return (
    <ol className="relative space-y-0">
      {steps.map((step, index) => {
        const last = index === steps.length - 1;
        const failed = step.failed;

        return (
          <li key={step.key || step.label} className="relative flex gap-3.5 pb-6 last:pb-0">
            {!last && (
              <span
                aria-hidden="true"
                className={cx(
                  'absolute left-[11px] top-6 h-[calc(100%-1.5rem)] w-0.5',
                  step.done && !failed ? 'bg-mint' : 'bg-line',
                )}
              />
            )}

            <span
              className={cx(
                'relative z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full border-2',
                failed
                  ? 'border-alert bg-alert text-white'
                  : step.done
                    ? 'border-mint bg-mint text-ink'
                    : step.current
                      ? 'border-mint bg-canvas'
                      : 'border-line bg-canvas',
              )}
            >
              {failed ? (
                <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none">
                  <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                </svg>
              ) : step.done ? (
                <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none">
                  <path
                    d="M5 10.5l3.5 3.5L15 7"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                <span
                  className={cx(
                    'h-1.5 w-1.5 rounded-full',
                    step.current ? 'animate-pulse bg-mint' : 'bg-line',
                  )}
                />
              )}
            </span>

            <div className="min-w-0 flex-1 pt-0.5">
              <p
                className={cx(
                  'text-sm font-medium',
                  failed
                    ? 'text-alert'
                    : step.done || step.current ? 'text-ink' : 'text-slate-light',
                )}
              >
                {step.label}
              </p>
              {step.at && (
                <p className="mt-0.5 text-2xs text-slate">
                  {new Date(step.at).toLocaleString('en-IN', {
                    day: 'numeric',
                    month: 'short',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true,
                  })}
                </p>
              )}
              {/* Free text, for a step whose useful detail is not a timestamp:
                  "usually within one working day", or the reason a step
                  failed. A state machine rendered as bare labels tells someone
                  waiting on a decision nothing they can act on. */}
              {step.detail && (
                <p
                  className={cx(
                    'mt-0.5 text-2xs',
                    failed ? 'text-alert' : 'text-slate',
                  )}
                >
                  {step.detail}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/* ── List link ──────────────────────────────────────────────────────────── */

export function ListLink({ icon, label, description, value, onClick, tone, danger }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3.5 px-1 py-3.5 text-left transition active:opacity-70"
    >
      {icon && (
        <span
          className={cx(
            'grid h-9 w-9 shrink-0 place-items-center rounded-xl',
            danger ? 'bg-red-50 text-alert' : 'bg-mist text-slate',
          )}
        >
          {icon}
        </span>
      )}

      <div className="min-w-0 flex-1">
        <p className={cx('text-sm font-medium', danger ? 'text-alert' : 'text-ink')}>
          {label}
        </p>
        {description && <p className="truncate text-xs text-slate">{description}</p>}
      </div>

      {value && (
        <span
          className={cx(
            'shrink-0 text-sm',
            tone === 'good' ? 'font-medium text-mint-700' : 'text-slate',
          )}
        >
          {value}
        </span>
      )}

      <IconChevron className="h-4 w-4 shrink-0 text-slate-light" />
    </button>
  );
}

export { BankLogo } from './BankLogo';

