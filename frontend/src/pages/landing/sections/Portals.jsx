import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';

import { cx } from '../../../components/ui';
import { ArrowRight, Container, EASE, SectionHeading, VIEWPORT } from './shared';

/**
 * The three ways in. Each portal has its own sign-in and only admits its own
 * role - the server refuses an account from another portal once its MPIN is
 * proven - so they are presented as three distinct doors, each with its own
 * accent, rather than one form with a role picker.
 */
export const PORTALS = [
  {
    key: 'user',
    title: 'Customers',
    cta: 'User login',
    path: '/signin',
    body: 'Your cards, credit line, EMIs, bills and payments in one view.',
    points: ['Sign up with your mobile number', 'MPIN sign-in, OTP to reset'],
    accent: 'bg-mint text-ink',
    ring: 'hover:border-mint-600/40',
    dot: 'bg-mint',
  },
  {
    key: 'admin',
    title: 'Administrators',
    cta: 'Admin login',
    path: '/admin/login',
    body: 'Users, KYC, credit decisions, payments, error logs and staff.',
    points: ['Risk & super-admin roles only', 'Every action is audited'],
    accent: 'bg-ink text-white',
    ring: 'hover:border-ink/30',
    dot: 'bg-ink',
  },
  {
    key: 'support',
    title: 'Customer support',
    cta: 'Support login',
    path: '/support-desk/login',
    body: 'Tickets, customer look-ups and escalations to the admin team.',
    points: ['Masked customer data', 'No access to money or limits'],
    accent: 'bg-sky-600 text-white',
    ring: 'hover:border-sky-400/50',
    dot: 'bg-sky-500',
  },
];

export function Portals() {
  const navigate = useNavigate();

  return (
    <section id="portals" className="scroll-mt-24 py-16 lg:py-24">
      <Container>
        <SectionHeading
          eyebrow="Sign in"
          title="Choose your portal"
          body="Customers, administrators and support agents each have their own door."
        />

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {PORTALS.map((portal, index) => (
            <motion.button
              key={portal.key}
              type="button"
              onClick={() => navigate(portal.path)}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={VIEWPORT}
              transition={{ duration: 0.55, ease: EASE, delay: index * 0.08 }}
              className={cx(
                'group flex flex-col rounded-3xl border border-line bg-canvas p-6 text-left shadow-card',
                'transition-[transform,box-shadow,border-color] duration-base ease-glide hover:-translate-y-1 hover:shadow-lift',
                portal.ring,
              )}
            >
              <span className="flex items-center gap-2 text-2xs font-bold uppercase tracking-[0.14em] text-slate">
                <span className={cx('h-2 w-2 rounded-full', portal.dot)} />
                {portal.title}
              </span>
              <span className="mt-3 block text-sm leading-relaxed text-slate">{portal.body}</span>
              <ul className="mt-4 flex-1 space-y-1.5">
                {portal.points.map((point) => (
                  <li key={point} className="text-xs text-ink">— {point}</li>
                ))}
              </ul>
              <span
                className={cx(
                  'mt-6 inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold',
                  portal.accent,
                )}
              >
                {portal.cta}
                <span className="transition-transform duration-base ease-glide group-hover:translate-x-0.5">
                  <ArrowRight />
                </span>
              </span>
            </motion.button>
          ))}
        </div>
      </Container>
    </section>
  );
}
