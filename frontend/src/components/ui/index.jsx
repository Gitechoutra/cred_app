/**
 * CashU UI primitives.
 *
 * Design contract: white dominates, mint is punctuation, motion is calm. Money
 * is always tabular so digits do not jitter while a value animates.
 */

import { useEffect, useRef, useState } from 'react';

export function cx(...parts) {
  return parts.filter(Boolean).join(' ');
}

/* ── Button ─────────────────────────────────────────────────────────────── */

/**
 * One button language for the whole app.
 *
 * Mint is the primary action colour - it was already carrying 45 of the 52 call
 * sites, so `primary` is now an alias for it rather than a second, competing
 * dark button. Every variant shares the same radius, weight, transition and
 * press animation; only the fill changes, and it changes for a reason: outline
 * and ghost are secondary, danger is destructive.
 */
const PRIMARY =
  'bg-mint text-ink shadow-mint hover:bg-mint-400 disabled:bg-mint-100 disabled:text-slate-light disabled:shadow-none';

const BUTTON_VARIANTS = {
  primary: PRIMARY,
  mint: PRIMARY,
  ghost: 'bg-transparent text-ink hover:bg-mist disabled:text-slate-light',
  outline:
    'bg-canvas text-ink border border-line hover:border-ink/25 hover:bg-mist disabled:text-slate-light',
  danger: 'bg-alert text-white hover:brightness-95 disabled:bg-slate-light',
};

/* Radius is deliberately constant across sizes - a 14px-tall pill next to a
   36px-tall rounded rectangle is the single loudest inconsistency in a UI. */
const BUTTON_SIZES = {
  sm: 'h-9 px-4 text-sm rounded-xl',
  md: 'h-11 px-5 text-sm rounded-xl',
  lg: 'h-14 px-6 text-base rounded-xl',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  full = false,
  className,
  children,
  disabled,
  ...props
}) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-2 font-semibold tracking-tight',
        'transition-all duration-150 ease-out active:scale-[0.97]',
        'disabled:cursor-not-allowed disabled:active:scale-100',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        full && 'w-full',
        className,
      )}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Spinner({ className = 'h-5 w-5' }) {
  return (
    <svg className={cx('animate-spin', className)} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* ── Input ──────────────────────────────────────────────────────────────── */

export function Input({
  label,
  hint,
  error,
  prefix,
  suffix,
  className,
  id,
  ...props
}) {
  const generated = useRef(`in-${Math.random().toString(36).slice(2, 9)}`);
  const inputId = id || generated.current;

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="mb-1.5 block text-sm font-medium text-ink">
          {label}
        </label>
      )}

      <div
        className={cx(
          'flex items-center gap-2 rounded-xl border bg-canvas px-3.5 transition-colors',
          'h-12',
          error ? 'border-alert' : 'border-line focus-within:border-ink/40',
        )}
      >
        {prefix && <span className="shrink-0 text-sm text-slate">{prefix}</span>}
        <input
          id={inputId}
          className={cx(
            'w-full bg-transparent text-[15px] text-ink outline-none',
            'placeholder:text-slate-light disabled:text-slate',
            className,
          )}
          aria-invalid={Boolean(error)}
          {...props}
        />
        {suffix && <span className="shrink-0 text-sm text-slate">{suffix}</span>}
      </div>

      {(error || hint) && (
        <p className={cx('mt-1.5 text-xs', error ? 'text-alert' : 'text-slate')}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

/* ── Card ───────────────────────────────────────────────────────────────── */

export function Card({ className, children, onClick, ...props }) {
  const interactive = Boolean(onClick);

  return (
    <div
      className={cx(
        'card-surface p-4',
        interactive && 'cursor-pointer transition-shadow hover:shadow-lift active:scale-[0.995]',
        className,
      )}
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onClick(event);
              }
            }
          : undefined
      }
      {...props}
    >
      {children}
    </div>
  );
}

/* ── Badge ──────────────────────────────────────────────────────────────── */

const BADGE_TONES = {
  good: 'bg-mint-50 text-mint-800 border-mint-200',
  warn: 'bg-amber-50 text-amber-700 border-amber-200',
  alert: 'bg-red-50 text-alert border-red-200',
  neutral: 'bg-mist text-slate border-line',
  ink: 'bg-ink text-white border-ink',
};

export function Badge({ tone = 'neutral', children, className, dot = false }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1',
        'text-2xs font-semibold uppercase tracking-wide',
        BADGE_TONES[tone],
        className,
      )}
    >
      {dot && (
        <span
          className={cx(
            'h-1.5 w-1.5 rounded-full',
            tone === 'good' && 'bg-mint-600',
            tone === 'warn' && 'bg-warn',
            tone === 'alert' && 'bg-alert',
            tone === 'neutral' && 'bg-slate-light',
          )}
        />
      )}
      {children}
    </span>
  );
}

/* ── Money ──────────────────────────────────────────────────────────────── */

/**
 * A monetary value that counts up once on mount.
 *
 * Once, deliberately - a number that re-animates on every render reads as
 * instability, which is the opposite of what a balance should feel like.
 */
export function AnimatedMoney({ value, className, duration = 500, format }) {
  const [display, setDisplay] = useState(0);
  const animated = useRef(false);

  useEffect(() => {
    const target = Number(value) || 0;

    if (animated.current) {
      setDisplay(target);
      return undefined;
    }
    animated.current = true;

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setDisplay(target);
      return undefined;
    }

    const start = performance.now();
    let frame;

    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      // Ease-out cubic: fast to begin, settling gently rather than stopping dead.
      const eased = 1 - (1 - progress) ** 3;
      setDisplay(target * eased);

      if (progress < 1) frame = requestAnimationFrame(tick);
      else setDisplay(target);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return <span className={cx('money', className)}>{format ? format(display) : display}</span>;
}

/* ── Sheet ──────────────────────────────────────────────────────────────── */

export function Sheet({ open, onClose, title, children, footer }) {
  useEffect(() => {
    if (!open) return undefined;

    const onKey = (event) => {
      if (event.key === 'Escape') onClose?.();
    };

    document.addEventListener('keydown', onKey);
    // Stop the page behind the sheet scrolling under the user's finger.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div
        className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx(
          'relative w-full max-w-md animate-sheet-up bg-canvas shadow-sheet',
          'rounded-t-3xl sm:rounded-3xl sm:animate-scale-in',
          'max-h-[92vh] flex flex-col',
        )}
      >
        <div className="shrink-0 px-5 pt-3">
          <div className="mx-auto h-1 w-10 rounded-full bg-line sm:hidden" />
          {title && (
            <div className="flex items-center justify-between pt-3 pb-1">
              <h2 className="text-lg font-semibold text-ink">{title}</h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="grid h-8 w-8 place-items-center rounded-full text-slate transition hover:bg-mist"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
                  <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          )}
        </div>

        <div className="sheet-scroll flex-1 overflow-y-auto px-5 py-3">{children}</div>

        {footer && <div className="shrink-0 border-t border-line px-5 py-4">{footer}</div>}
      </div>
    </div>
  );
}

/* ── Skeleton & empty states ────────────────────────────────────────────── */

export function Skeleton({ className }) {
  return <div className={cx('skeleton', className)} aria-hidden="true" />;
}

export function EmptyState({ icon, title, description, action, className }) {
  return (
    <div className={cx('flex flex-col items-center px-6 py-12 text-center', className)}>
      {icon && (
        <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-mist text-slate">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description && <p className="mt-1.5 max-w-xs text-sm text-slate">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ── Section ────────────────────────────────────────────────────────────── */

export function Section({ title, action, children, className }) {
  return (
    <section className={cx('space-y-3', className)}>
      {(title || action) && (
        <div className="flex items-center justify-between px-1">
          {title && (
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate">
              {title}
            </h2>
          )}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/* ── Row ────────────────────────────────────────────────────────────────── */

export function Row({ label, value, tone, className, mono = false }) {
  return (
    <div className={cx('flex items-baseline justify-between gap-4 py-2', className)}>
      <span className="text-sm text-slate">{label}</span>
      <span
        className={cx(
          'text-sm font-medium text-right',
          mono && 'money',
          tone === 'good' && 'text-mint-700',
          tone === 'alert' && 'text-alert',
          !tone && 'text-ink',
        )}
      >
        {value}
      </span>
    </div>
  );
}

/* ── Progress ───────────────────────────────────────────────────────────── */

/**
 * Utilization meter.
 *
 * The one place colour encodes data. No red-to-green gradient - this is a debt
 * app, and a wall of red reads as judgement rather than information.
 */
export function Meter({ value = 0, tone = 'good', className, showLabel = false }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));

  const fill = {
    good: 'bg-mint',
    neutral: 'bg-slate-light',
    warn: 'bg-warn',
    alert: 'bg-alert',
  }[tone];

  return (
    <div className={className}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-mist">
        <div
          className={cx('h-full rounded-full transition-all duration-700', fill)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {showLabel && <p className="mt-1 text-2xs text-slate money">{pct.toFixed(0)}% used</p>}
    </div>
  );
}

/* ── Toggle ─────────────────────────────────────────────────────────────── */

export function Toggle({ checked, onChange, disabled, label, description }) {
  return (
    <label
      className={cx(
        'flex items-start justify-between gap-4 py-3',
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
      )}
    >
      <span className="flex-1">
        <span className="block text-sm font-medium text-ink">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-slate">{description}</span>}
      </span>

      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange?.(!checked)}
        className={cx(
          'relative mt-0.5 h-6 w-11 shrink-0 rounded-full overflow-hidden transition-colors focus:outline-none',
          checked ? 'bg-mint' : 'bg-line',
        )}
      >
        <span
          className={cx(
            'pointer-events-none absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 ease-in-out',
            checked ? 'translate-x-5' : 'translate-x-0',
          )}
        />
      </button>
    </label>
  );
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */

export function Tabs({ tabs, active, onChange, className }) {
  return (
    <div className={cx('flex gap-1 rounded-xl bg-mist p-1', className)} role="tablist">
      {tabs.map((tab) => {
        const value = tab.value ?? tab;
        const label = tab.label ?? tab;
        const selected = value === active;

        return (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(value)}
            className={cx(
              'flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-all',
              selected ? 'bg-canvas text-ink shadow-sm' : 'text-slate hover:text-ink',
            )}
          >
            {label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-2xs text-slate-light money">{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
