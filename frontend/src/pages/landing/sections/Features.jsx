import { motion } from 'motion/react';

import {
  IconBell, IconCard, IconChart, IconLock, IconReceipt,
} from '../../../components/layout/AppShell';
import { cx } from '../../../components/ui';
import { MOCK_CARDS } from './Hero';
import { Container, EASE, FadeIn, SectionHeading, VIEWPORT } from './shared';

/**
 * The five things the dashboard does for a cardholder, as a bento grid. Each
 * is a feature that exists in the app today; the miniatures use illustrative
 * figures, not anyone's data.
 */
export function Features() {
  return (
    <section id="features" className="relative border-t border-line bg-[linear-gradient(180deg,#F7F8FA_0%,#FFFFFF_100%)] py-16 lg:py-24">
      <Container className="relative">
        <SectionHeading
          eyebrow="Features"
          title="Everything your cards need, in one place"
          body="Five essentials, done properly - from what you owe to when it is due."
        />

        <div className="mt-12 grid gap-4 lg:grid-cols-6">
          <Tile className="lg:col-span-4" icon={IconCard} title="Credit Card Management"
            body="Add every card you hold - tokenised with a CashU limit, or tracked by hand with the figures you know. Bank, nickname, masked number, limit and balance, side by side."
          >
            <CardList />
          </Tile>
          <Tile className="lg:col-span-2" icon={IconChart} title="Credit Utilization Tracking"
            body="See how much of each limit you are using, and keep it under the 30% lenders like to see." delay={80}
          >
            <Utilisation />
          </Tile>
          <Tile className="lg:col-span-2" icon={IconBell} title="Bill Reminders"
            body="Every due date in one view, with reminders before each one so a payment is never missed." delay={40}
          >
            <Reminders />
          </Tile>
          <Tile className="lg:col-span-2" icon={IconReceipt} title="Payment History"
            body="Every payment with its status and reference - successful, pending or failed - confirmed by the payment gateway, never by the app." delay={110}
          >
            <History />
          </Tile>
          <Tile className="lg:col-span-2" icon={IconLock} title="Secure Account Access"
            body="Mobile + 6-digit MPIN, sessions you can sign out remotely, and no full card number, CVV or PIN ever stored." delay={180}
          >
            <SecureAccess />
          </Tile>
        </div>
      </Container>
    </section>
  );
}

function Tile({ icon: Icon, title, body, className, delay = 0, children }) {
  return (
    <FadeIn delay={delay} className={cx('h-full', className)}>
      <article className="lp-silver-edge group relative flex h-full flex-col overflow-hidden rounded-3xl border border-line bg-canvas p-6 shadow-card transition-all duration-slow ease-glide hover:-translate-y-1 hover:shadow-lift">
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-ink text-white transition-transform duration-base ease-glide group-hover:scale-110">
          <Icon className="h-5 w-5" />
        </span>
        <h3 className="mt-4 text-base font-bold text-ink">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate">{body}</p>
        {children && <div className="mt-auto pt-6" aria-hidden="true">{children}</div>}
      </article>
    </FadeIn>
  );
}

/* ── Miniatures (illustrative figures) ─────────────────────────────────── */

const ROWS = [
  { card: MOCK_CARDS[0], name: 'Signature Black', limit: '₹3,00,000', owed: '₹48,200', used: 0.16 },
  { card: MOCK_CARDS[1], name: 'Ocean Platinum', limit: '₹1,50,000', owed: '₹61,500', used: 0.41 },
  { card: MOCK_CARDS[3], name: 'Teal Travel', limit: '₹80,000', owed: '₹6,315', used: 0.08 },
];

function Bar({ share, index, tone = 'bg-ink' }) {
  return (
    <span className="block h-1.5 flex-1 overflow-hidden rounded-full bg-mist">
      <motion.span
        className={cx('block h-full origin-left rounded-full', tone)}
        style={{ width: `${Math.round(share * 100)}%` }}
        initial={{ scaleX: 0 }}
        whileInView={{ scaleX: 1 }}
        viewport={VIEWPORT}
        transition={{ duration: 0.9, ease: EASE, delay: 0.2 + index * 0.1 }}
      />
    </span>
  );
}

function CardList() {
  return (
    <ul className="grid gap-2.5 sm:grid-cols-3">
      {ROWS.map((row) => (
        <li key={row.name} className="rounded-2xl border border-line bg-canvas p-3">
          <span className="block h-14 rounded-xl shadow-card" style={{ backgroundImage: row.card.gradient }} />
          <p className="mt-2.5 truncate text-xs font-semibold text-ink">{row.name}</p>
          <p className="money text-2xs text-slate">•••• {row.card.last4}</p>
          <div className="mt-2 flex items-baseline justify-between text-2xs">
            <span className="text-slate">Limit</span>
            <span className="money font-semibold text-ink">{row.limit}</span>
          </div>
          <div className="flex items-baseline justify-between text-2xs">
            <span className="text-slate">Outstanding</span>
            <span className="money font-semibold text-ink">{row.owed}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function Utilisation() {
  return (
    <ul className="space-y-3">
      {ROWS.map((row, index) => (
        <li key={row.name}>
          <div className="mb-1 flex justify-between text-2xs">
            <span className="font-medium text-ink">{row.name}</span>
            <span className={cx('money font-semibold', row.used > 0.3 ? 'text-warn' : 'text-ink')}>
              {Math.round(row.used * 100)}%
            </span>
          </div>
          <Bar share={row.used} index={index} tone={row.used > 0.3 ? 'bg-warn' : 'bg-ink'} />
        </li>
      ))}
    </ul>
  );
}

function Reminders() {
  const items = [
    { when: 'In 3 days', what: 'Signature Black · ₹48,200', strong: true },
    { when: '12 Nov', what: 'Ocean Platinum · minimum ₹3,075' },
  ];
  return (
    <ul className="space-y-2">
      {items.map((it) => (
        <li key={it.what} className="flex items-center gap-3 rounded-2xl border border-line bg-canvas px-3 py-2.5">
          <span className={cx('grid h-8 w-8 shrink-0 place-items-center rounded-xl',
            it.strong ? 'bg-ink text-white' : 'bg-mist text-ink')}
          >
            <IconBell className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className={cx('block text-2xs font-semibold', it.strong ? 'text-warn' : 'text-slate')}>{it.when}</span>
            <span className="block truncate text-xs text-ink">{it.what}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function History() {
  const rows = [
    ['Bill payment', '₹12,940', 'Successful', 'text-mint-800 bg-mint-50'],
    ['EMI · Bajaj Finance', '₹4,250', 'Successful', 'text-mint-800 bg-mint-50'],
    ['Bill payment', '₹2,100', 'Pending', 'text-amber-800 bg-amber-50'],
  ];
  return (
    <ul className="divide-y divide-line rounded-2xl border border-line bg-canvas">
      {rows.map(([what, amount, status, tone], index) => (
        <li key={index} className="flex items-center justify-between gap-2 px-3 py-2.5">
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium text-ink">{what}</span>
            <span className={cx('mt-0.5 inline-block rounded-full px-1.5 text-[10px] font-semibold', tone)}>{status}</span>
          </span>
          <span className="money shrink-0 text-xs font-bold text-ink">{amount}</span>
        </li>
      ))}
    </ul>
  );
}

function SecureAccess() {
  return (
    <div className="rounded-2xl bg-[linear-gradient(150deg,#1B1F1E_0%,#0A0F0D_100%)] p-4 text-white">
      <div className="flex items-center justify-between">
        <p className="text-2xs font-semibold text-white/70">Enter MPIN</p>
        <IconLock className="h-4 w-4 text-white/70" />
      </div>
      <div className="mt-3 flex gap-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <motion.span
            key={i}
            className="h-2.5 w-2.5 rounded-full bg-white"
            initial={{ opacity: 0.2, scale: 0.6 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={VIEWPORT}
            transition={{ duration: 0.3, ease: EASE, delay: 0.3 + i * 0.08 }}
          />
        ))}
      </div>
      <p className="mt-3 border-t border-white/10 pt-3 text-2xs text-white/55">
        Card numbers tokenised · sessions revocable · every sign-in logged
      </p>
    </div>
  );
}
