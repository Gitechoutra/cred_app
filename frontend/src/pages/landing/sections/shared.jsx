import { motion } from 'motion/react';

import { cx } from '../../../components/ui';

/**
 * Pieces every landing section shares.
 *
 * One easing curve and one reveal so the page moves as a single system. The
 * curve is the app's `glide` (tailwind.config.js), so the marketing page and
 * the product it advertises feel like the same thing.
 */

export const EASE = [0.16, 1, 0.3, 1];

/** Reveal once, a little way into the viewport, then never again. */
export const VIEWPORT = { once: true, margin: '0px 0px -60px 0px' };

export function Container({ className, children }) {
  return (
    <div className={cx('mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8', className)}>
      {children}
    </div>
  );
}

/** Rises into place on first sight. `MotionConfig reducedMotion="user"` drops the travel. */
export function FadeIn({ delay = 0, y = 16, className, children, as = 'div' }) {
  const Tag = motion[as];
  return (
    <Tag
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={VIEWPORT}
      transition={{ duration: 0.6, ease: EASE, delay: delay / 1000 }}
    >
      {children}
    </Tag>
  );
}

export function Eyebrow({ icon: Icon, tone = 'mint', children }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-2xs font-bold uppercase tracking-[0.14em]',
        tone === 'mint'
          ? 'lp-silver-chip border-[#D5DBE1] text-ink'
          : 'border-white/15 bg-white/5 text-[#C9D1DA]',
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5" />}
      {children}
    </span>
  );
}

export function SectionHeading({ eyebrow, icon, title, body, align = 'center', className }) {
  return (
    <FadeIn
      className={cx(
        'max-w-2xl',
        align === 'center' ? 'mx-auto text-center' : 'text-left',
        className,
      )}
    >
      {eyebrow && <Eyebrow icon={icon}>{eyebrow}</Eyebrow>}
      <h2 className="mt-5 text-3xl font-bold tracking-tight text-ink sm:text-4xl">{title}</h2>
      {body && <p className="mt-4 text-base leading-relaxed text-slate">{body}</p>}
    </FadeIn>
  );
}

export function CheckMark({ className = 'h-3 w-3', strokeWidth = 3 }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="none" aria-hidden="true">
      <path
        d="M5 10.5l3.5 3.5L15 7"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ArrowRight({ className = 'h-4 w-4' }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="none" aria-hidden="true">
      <path
        d="M4 10h11M11 5l5 5-5 5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
