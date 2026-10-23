import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  motion, useMotionValue, useReducedMotion, useSpring, useTransform,
} from 'motion/react';

import { CreditCard } from '../../../components/marketing/Showcase';
import { Button } from '../../../components/ui';
import { LoginCards } from './Portals';
import { ArrowRight, CheckMark, Container, EASE } from './shared';

const ASSURANCES = ['Card numbers never stored', 'Mobile + MPIN sign-in', 'Free to track'];

/**
 * Four card mockups in bank-inspired colours. Illustrative only: no real card
 * numbers, and the labels are generic rather than real card products.
 */
export const MOCK_CARDS = [
  { label: 'Signature Black', network: 'visa', last4: '4821',
    gradient: 'linear-gradient(135deg,#2B2F2E 0%,#121514 55%,#050606 100%)', sheen: true },
  { label: 'Ocean Platinum', network: 'mastercard', last4: '7710',
    gradient: 'linear-gradient(135deg,#2563EB 0%,#1E40AF 50%,#0B2A6B 100%)' },
  { label: 'Royal Rewards', network: 'visa', last4: '3094',
    gradient: 'linear-gradient(135deg,#7C4DE0 0%,#4C2A9E 55%,#2E1466 100%)' },
  { label: 'Teal Travel', network: 'mastercard', last4: '5562',
    gradient: 'linear-gradient(135deg,#14A89C 0%,#0E7A72 50%,#04403D 100%)' },
];

const stack = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
};
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
};
const line = {
  hidden: { y: '110%' },
  show: { y: '0%', transition: { duration: 0.8, ease: EASE } },
};

export function Hero() {
  const navigate = useNavigate();

  return (
    <section id="top" className="relative isolate">
      {/* White, with a silver wash and a faint dot field - no colour glow. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <span className="absolute inset-x-0 top-0 h-[42rem] bg-[radial-gradient(ellipse_at_top,#EEF1F4_0%,rgba(255,255,255,0)_70%)]" />
        <span className="orb animate-drift-slow right-[-10rem] top-16 h-[24rem] w-[24rem] bg-[#C9D1DA]/40" />
        <span className="orb animate-drift -left-32 top-48 h-[18rem] w-[18rem] bg-[#DDE3EA]/50" />
        <span className="lp-dots absolute inset-0 opacity-50" />
      </div>

      <Container className="grid grid-cols-1 items-center gap-10 pb-6 pt-10 lg:grid-cols-[1.05fr_1fr] lg:gap-8 lg:pt-16">
        <motion.div variants={stack} initial="hidden" animate="show">
          <motion.span
            variants={item}
            className="lp-silver-chip inline-flex items-center gap-2 rounded-full border border-[#D5DBE1] px-3 py-1.5 text-2xs font-semibold text-ink"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-ink" />
            Credit card management, simplified
          </motion.span>

          <h1 className="mt-6 text-[2.6rem] font-bold leading-[1.04] tracking-[-0.025em] text-ink sm:text-[3.4rem] lg:text-[3.5rem] xl:text-[3.9rem]">
            <span className="block overflow-hidden pb-1">
              <motion.span variants={line} className="block">Your Credit Cards.</motion.span>
            </span>
            <span className="block overflow-hidden pb-2">
              <motion.span variants={line} className="lp-silver-text block">One Smart Dashboard.</motion.span>
            </span>
          </h1>

          <motion.p variants={item} className="mt-6 max-w-lg text-base leading-relaxed text-slate sm:text-lg">
            Keep every credit card in one secure place. See limits, outstanding
            balances and utilisation at a glance, get reminded before each bill
            is due, and keep your payment history in one clear record.
          </motion.p>

          <motion.div variants={item} className="mt-8 flex flex-wrap gap-3">
            <Button
              variant="dark"
              size="lg"
              className="group"
              onClick={() => navigate('/signin')}
            >
              Get started free
              <span className="transition-transform duration-base ease-glide group-hover:translate-x-0.5">
                <ArrowRight />
              </span>
            </Button>
            <Button variant="outline" size="lg" onClick={() => {
              document.getElementById('portals')?.scrollIntoView({ behavior: 'smooth' });
            }}
            >
              Choose how to sign in
            </Button>
          </motion.div>

          <motion.ul variants={item} className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
            {ASSURANCES.map((point) => (
              <li key={point} className="flex items-center gap-1.5 text-2xs text-slate">
                <CheckMark className="h-3.5 w-3.5 text-ink" strokeWidth={2.5} />
                {point}
              </li>
            ))}
          </motion.ul>
        </motion.div>

        <CardFan />
      </Container>

      <Container className="pb-16 pt-6 lg:pb-24">
        <div id="portals" className="scroll-mt-24">
          <LoginCards />
        </div>
      </Container>
    </section>
  );
}

/**
 * Four cards fanned out. They lean a little after the pointer, spread on
 * hover, and settle into a plain stack where motion is reduced.
 */
function CardFan() {
  const reduce = useReducedMotion();
  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);
  const rotateY = useSpring(useTransform(pointerX, [-1, 1], [-8, 8]), { stiffness: 80, damping: 16 });
  const rotateX = useSpring(useTransform(pointerY, [-1, 1], [6, -6]), { stiffness: 80, damping: 16 });

  useEffect(() => {
    const coarse = window.matchMedia?.('(pointer: coarse)').matches;
    if (reduce || coarse) return undefined;
    const onMove = (event) => {
      pointerX.set(event.clientX / window.innerWidth * 2 - 1);
      pointerY.set(event.clientY / window.innerHeight * 2 - 1);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [reduce, pointerX, pointerY]);

  // Resting positions, back card first. Hover spreads them a little further.
  const poses = [
    { x: -84, y: 52, r: -14 },
    { x: -28, y: 18, r: -6 },
    { x: 28, y: -14, r: 3 },
    { x: 84, y: -46, r: 11 },
  ];

  return (
    <motion.div
      className="lp-fan group relative mx-auto h-[300px] w-full max-w-[520px] sm:h-[360px]"
      style={{ rotateX, rotateY, transformPerspective: 1200 }}
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.9, ease: EASE, delay: 0.15 }}
      aria-label="Illustrative credit card designs in black, blue, purple and teal"
      role="img"
    >
      <span aria-hidden="true" className="absolute inset-x-10 bottom-4 h-10 rounded-full bg-ink/15 blur-2xl" />
      {MOCK_CARDS.map((card, index) => {
        const pose = poses[index];
        return (
          // The entrance animates this wrapper's transform; the fan pose lives
          // on the inner element, so the two never overwrite each other.
          <motion.div
            key={card.label}
            className="absolute left-1/2 top-1/2"
            style={{ zIndex: index }}
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: EASE, delay: 0.25 + index * 0.1 }}
          >
            <div
              className="lp-fan-card"
              style={{ '--fx': `${pose.x}px`, '--fy': `${pose.y}px`, '--fr': `${pose.r}deg` }}
            >
              <CreditCard
                label={card.label}
                network={card.network}
                last4={card.last4}
                gradient={card.gradient}
                sheen={card.sheen}
                className="w-56 sm:w-64"
              />
            </div>
          </motion.div>
        );
      })}

      {/* Two quiet figures, so the fan reads as a dashboard and not a poster.
          Illustrative values. */}
      <motion.div
        aria-hidden="true"
        className="absolute -left-1 top-6 hidden rounded-2xl border border-line bg-canvas/95 px-3.5 py-2.5 shadow-lift backdrop-blur sm:block"
        initial={{ opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.8 }}
      >
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate">Utilisation</p>
        <p className="money text-lg font-bold text-ink">22%</p>
        <span className="mt-1 block h-1 w-24 overflow-hidden rounded-full bg-mist">
          <span className="block h-full w-[22%] rounded-full bg-ink" />
        </span>
      </motion.div>
      <motion.div
        aria-hidden="true"
        className="absolute -right-1 bottom-8 hidden rounded-2xl border border-line bg-canvas/95 px-3.5 py-2.5 shadow-lift backdrop-blur sm:block"
        initial={{ opacity: 0, x: 12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.95 }}
      >
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate">Next bill</p>
        <p className="money text-lg font-bold text-ink">₹12,940</p>
        <p className="text-[10px] text-slate">Due in 3 days</p>
      </motion.div>
    </motion.div>
  );
}
