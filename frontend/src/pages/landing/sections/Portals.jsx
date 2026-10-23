import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';

import { IconHelp, IconShield, IconUser } from '../../../components/layout/AppShell';
import { cx } from '../../../components/ui';
import { ArrowRight, EASE, VIEWPORT } from './shared';

/**
 * The three ways in. Each opens the existing sign-in screen for that role -
 * the same mobile + MPIN system behind all three - and each portal only
 * admits its own role: the server refuses an account from another portal once
 * its MPIN is proven, and every console endpoint checks the role itself.
 */
export const PORTALS = [
  {
    key: 'user',
    title: 'User Login',
    path: '/signin',
    icon: IconUser,
    body: 'Your personal dashboard: credit cards, limits, outstanding balances, due dates, bills and transaction history.',
    note: 'New here? Sign up with your mobile number.',
    tone: 'dark',
  },
  {
    key: 'admin',
    title: 'Admin Login',
    path: '/admin/login',
    icon: IconShield,
    body: 'The secure admin console: manage users, monitor card records, review transactions and run operations.',
    note: 'Administrator accounts only.',
    tone: 'silver',
  },
  {
    key: 'support',
    title: 'Customer Support Login',
    path: '/support-desk/login',
    icon: IconHelp,
    body: 'The support desk: customer queries, support tickets, complaints and escalations to the admin team.',
    note: 'Support agent accounts only.',
    tone: 'light',
  },
];

const TONES = {
  // Black card with a silver edge - the primary door.
  dark: {
    card: 'bg-[linear-gradient(150deg,#1B1F1E_0%,#0A0F0D_60%,#000_100%)] text-white border-white/10',
    icon: 'bg-white/10 text-white ring-1 ring-white/15',
    body: 'text-white/65',
    note: 'text-white/45',
    button: 'bg-white text-ink group-hover:bg-[#E9ECEF]',
  },
  // Brushed silver.
  silver: {
    card: 'bg-[linear-gradient(150deg,#FFFFFF_0%,#EEF1F4_55%,#DDE3E9_100%)] text-ink border-[#D5DBE1]',
    icon: 'bg-ink text-white',
    body: 'text-slate',
    note: 'text-slate',
    button: 'bg-ink text-white group-hover:bg-ink/90',
  },
  // White with a hairline.
  light: {
    card: 'bg-canvas text-ink border-line',
    icon: 'bg-[linear-gradient(150deg,#EEF1F4,#D5DBE1)] text-ink ring-1 ring-[#D5DBE1]',
    body: 'text-slate',
    note: 'text-slate',
    button: 'bg-ink text-white group-hover:bg-ink/90',
  },
};

export function LoginCards() {
  const navigate = useNavigate();

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-2xs font-bold uppercase tracking-[0.16em] text-slate">Sign in</p>
          <h2 className="mt-1 text-xl font-bold tracking-tight text-ink sm:text-2xl">Choose your portal</h2>
        </div>
        <p className="text-xs text-slate">Each portal opens its own secure sign-in.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {PORTALS.map((portal, index) => {
          const tone = TONES[portal.tone];
          const Icon = portal.icon;
          return (
            <motion.button
              key={portal.key}
              type="button"
              data-portal={portal.key}
              onClick={() => navigate(portal.path)}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={VIEWPORT}
              transition={{ duration: 0.55, ease: EASE, delay: 0.1 + index * 0.08 }}
              className={cx(
                'lp-silver-edge group flex flex-col rounded-3xl border p-6 text-left shadow-card',
                'transition-[transform,box-shadow] duration-base ease-glide hover:-translate-y-1 hover:shadow-lift',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2',
                tone.card,
              )}
            >
              <span className={cx(
                'grid h-11 w-11 place-items-center rounded-2xl transition-transform duration-base ease-glide group-hover:scale-105',
                tone.icon,
              )}
              >
                <Icon className="h-5 w-5" />
              </span>
              <span className="mt-4 block text-base font-bold">{portal.title}</span>
              <span className={cx('mt-2 block flex-1 text-sm leading-relaxed', tone.body)}>{portal.body}</span>
              <span className={cx('mt-4 block text-2xs', tone.note)}>{portal.note}</span>
              <span
                className={cx(
                  'mt-4 inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold transition-colors duration-base',
                  tone.button,
                )}
              >
                {portal.title}
                <span className="transition-transform duration-base ease-glide group-hover:translate-x-0.5">
                  <ArrowRight />
                </span>
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
