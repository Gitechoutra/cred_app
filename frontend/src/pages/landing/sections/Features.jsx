import { motion } from 'motion/react';

import { bankCardTheme } from '../../../components/domain/BankLogo';
import {
  IconBill, IconCard, IconChart, IconEmi, IconPay, IconQr,
} from '../../../components/layout/AppShell';
import { cx } from '../../../components/ui';
import { Container, EASE, FadeIn, SectionHeading, VIEWPORT } from './shared';

/**
 * What the product does, as a bento grid.
 *
 * Every tile is a feature that exists in the app today, and every figure in
 * the miniatures is illustrative rather than a claim. The two large tiles carry
 * a small live-looking view of the screen they describe, because "see every due
 * date at once" is more convincing shown than said.
 */
export function Features() {
  return (
    <section id="features" className="relative border-t border-line bg-mist/40 py-16 lg:py-24">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <span className="orb animate-drift-slow -right-32 top-20 h-80 w-80 bg-mint/15" />
      </div>

      <Container className="relative">
        <SectionHeading
          eyebrow="Features"
          title="Built for the way Indian credit actually works"
          body="Six things, done properly, instead of forty done partly."
        />

        <div className="mt-12 grid gap-4 lg:grid-cols-6">
          <Tile
            className="lg:col-span-4"
            icon={IconCard}
            title="Every card, one dashboard"
            body="Link cards from HDFC, ICICI, SBI, Axis and more. Limits, utilisation and due dates sit side by side, with reminders seven days and one day before each payment."
          >
            <DueList />
          </Tile>

          <Tile
            className="lg:col-span-2"
            icon={IconEmi}
            title="EMIs that pay themselves"
            body="Track loans from Bajaj Finance and other lenders. Pay over UPI or netbanking, or arm an NPCI e-mandate."
            delay={80}
          >
            <MandateChip />
          </Tile>

          <Tile
            className="lg:col-span-2"
            icon={IconPay}
            title="A CashU credit line"
            body="Apply in minutes. Your limit is worked out from your salary and bureau score, with statements every month."
          />
          <Tile
            className="lg:col-span-2"
            icon={IconQr}
            title="Scan & Pay"
            body="Point the camera at any UPI QR and pay it from your credit line. The code is checked on our server before you confirm."
            delay={70}
          />
          <Tile
            className="lg:col-span-2"
            icon={IconBill}
            title="Pay Bills"
            body="Settle rent, fees and other bills from your credit line into your own verified account. Every fee is shown before the OTP."
            delay={140}
          />

          <Tile
            className="lg:col-span-6"
            icon={IconChart}
            title="Know your credit score"
            body="Pull your score from the credit bureau and see the factors that move it, before a lender sees it first."
            wide
          >
            <ScoreGauge score={762} />
          </Tile>
        </div>
      </Container>
    </section>
  );
}

function Tile({ icon: Icon, title, body, className, delay = 0, wide = false, children }) {
  return (
    <FadeIn delay={delay} className={cx('h-full', className)}>
      <article
        className={cx(
          'group edge-glow relative flex h-full flex-col overflow-hidden rounded-3xl border border-line bg-canvas/85 p-6 backdrop-blur',
          'transition-all duration-slow ease-glide hover:-translate-y-1 hover:shadow-lift',
          wide && 'md:flex-row md:items-center md:gap-10',
        )}
      >
        <span aria-hidden="true" className="shine absolute inset-0" />

        <div className={cx('relative', wide && 'md:flex-1')}>
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-ink text-mint transition-all duration-base ease-glide group-hover:scale-110 group-hover:bg-mint group-hover:text-ink group-hover:shadow-mint">
            <Icon className="h-5 w-5" />
          </span>
          <h3 className="mt-4 text-base font-bold text-ink">{title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate">{body}</p>
        </div>

        {children && (
          <div className={cx('relative mt-6', wide ? 'md:mt-0 md:w-72' : 'mt-auto pt-6')} aria-hidden="true">
            {children}
          </div>
        )}
      </article>
    </FadeIn>
  );
}

/* ── Miniatures ─────────────────────────────────────────────────────────── */

const DUES = [
  { bank: 'hdfc', name: 'HDFC Regalia', due: 'in 3 days', amount: '₹48,200', used: 0.22 },
  { bank: 'icici', name: 'ICICI Sapphiro', due: '12 Nov', amount: '₹12,940', used: 0.41 },
  { bank: 'sbi', name: 'SBI SimplyCLICK', due: '19 Nov', amount: '₹6,315', used: 0.08 },
];

function DueList() {
  return (
    <ul className="space-y-2.5">
      {DUES.map((row, index) => {
        const theme = bankCardTheme(row.bank);
        return (
          <li key={row.name} className="flex items-center gap-3 rounded-2xl border border-line bg-canvas p-3">
            <span
              className="h-8 w-12 shrink-0 rounded-md shadow-card"
              style={{ backgroundImage: `linear-gradient(135deg, ${theme.from}, ${theme.to})` }}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-xs font-semibold text-ink">{row.name}</p>
                <p className="money shrink-0 text-xs font-bold text-ink">{row.amount}</p>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="h-1 flex-1 overflow-hidden rounded-full bg-mist">
                  <motion.span
                    className="block h-full origin-left rounded-full bg-mint"
                    style={{ width: `${row.used * 100}%` }}
                    initial={{ scaleX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    viewport={VIEWPORT}
                    transition={{ duration: 0.9, ease: EASE, delay: 0.2 + index * 0.1 }}
                  />
                </span>
                <span className={cx('shrink-0 text-2xs', index === 0 ? 'font-semibold text-warn' : 'text-slate')}>
                  Due {row.due}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function MandateChip() {
  return (
    <div className="rounded-2xl bg-ink p-4 text-white">
      <div className="flex items-center justify-between">
        <p className="text-2xs font-bold text-mint">Auto-pay armed</p>
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-mint" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-mint" />
        </span>
      </div>
      <p className="money mt-2 text-xl font-bold tracking-tight">₹4,250</p>
      <p className="mt-0.5 text-2xs text-white/55">Bajaj Finance · 5th of every month</p>
      <p className="mt-3 border-t border-white/10 pt-3 text-2xs text-white/55">
        Notice 48h before each debit · pause anytime
      </p>
    </div>
  );
}

/** A 300–900 bureau gauge whose arc draws itself on first sight. */
function ScoreGauge({ score }) {
  const share = (score - 300) / 600;
  return (
    <div className="flex items-center gap-5 rounded-2xl border border-line bg-canvas p-4">
      <svg viewBox="0 0 120 70" className="w-32 shrink-0">
        <path d="M10 62a50 50 0 0 1 100 0" fill="none" stroke="#E6EAE8" strokeWidth="10" strokeLinecap="round" />
        <motion.path
          d="M10 62a50 50 0 0 1 100 0"
          fill="none"
          stroke="#00F5B8"
          strokeWidth="10"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          whileInView={{ pathLength: share }}
          viewport={VIEWPORT}
          transition={{ duration: 1.2, ease: EASE, delay: 0.2 }}
        />
      </svg>
      <div>
        <p className="money text-3xl font-bold tracking-tight text-ink">{score}</p>
        <p className="text-2xs font-semibold text-mint-800">Excellent</p>
        <p className="mt-1 text-2xs text-slate">Illustrative score</p>
      </div>
    </div>
  );
}
