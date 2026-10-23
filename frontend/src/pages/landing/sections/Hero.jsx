import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  motion, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform,
} from 'motion/react';

import Showcase from '../../../components/marketing/Showcase';
import { Button } from '../../../components/ui';
import { ArrowRight, CheckMark, Container, EASE } from './shared';

const HEADLINE = ['Every card.', 'Every EMI.'];
const ASSURANCES = ['No password to remember', 'Zero card data stored', 'Free to track'];

const stack = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
};
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
};
// Headline lines rise from behind their own baseline (the wrapper clips), so
// they read as typeset rather than faded in.
const line = {
  hidden: { y: '110%' },
  show: { y: '0%', transition: { duration: 0.8, ease: EASE } },
};

export function Hero() {
  const navigate = useNavigate();

  return (
    <section id="top" className="relative isolate">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <span className="orb animate-drift -left-24 -top-32 h-[26rem] w-[26rem] bg-mint/30" />
        <span className="orb animate-drift-slow right-[-8rem] top-10 h-[22rem] w-[22rem] bg-mint-300/25" />
        <span className="orb animate-drift-slow bottom-[-10rem] left-1/3 h-[20rem] w-[20rem] bg-mint-200/30" />
        <span className="lp-dots absolute inset-0 opacity-60" />
      </div>

      <Container className="grid grid-cols-1 items-center gap-4 pb-8 pt-10 lg:grid-cols-[1.05fr_1fr] lg:gap-8 lg:pb-20 lg:pt-16">
        <motion.div variants={stack} initial="hidden" animate="show">
          <motion.span
            variants={item}
            className="inline-flex items-center gap-2 rounded-full border border-mint-200 bg-mint-50/80 px-3 py-1.5 text-2xs font-semibold text-mint-800 backdrop-blur"
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-mint-600" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-mint-600" />
            </span>
            RBI Card-on-File tokenisation
          </motion.span>

          <h1 className="mt-6 text-[2.75rem] font-bold leading-[1.05] tracking-[-0.02em] text-ink sm:text-[3.5rem] lg:text-[4rem]">
            {HEADLINE.map((text) => (
              <span key={text} className="block overflow-hidden pb-1">
                <motion.span variants={line} className="block">{text}</motion.span>
              </span>
            ))}
            <span className="block overflow-hidden pb-2">
              <motion.span variants={line} className="relative inline-block">
                <span className="relative z-10">One view.</span>
                <motion.span
                  aria-hidden="true"
                  className="absolute -bottom-0.5 left-0 h-4 w-full origin-left -skew-x-6 rounded-sm bg-mint/40"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.7, ease: EASE, delay: 0.75 }}
                />
              </motion.span>
            </span>
          </h1>

          <motion.p variants={item} className="mt-6 max-w-lg text-base leading-relaxed text-slate sm:text-lg">
            Track what you owe across every credit card and loan, pay it without
            hunting through six different portals, and get a CashU credit line
            with a limit worked out from your salary and credit score.
          </motion.p>

          <motion.div variants={item} className="mt-8 flex flex-wrap gap-3">
            <Button variant="mint" size="lg" className="group" onClick={() => navigate('/signin')}>
              Get started — it&rsquo;s free
              <span className="transition-transform duration-base ease-glide group-hover:translate-x-0.5">
                <ArrowRight />
              </span>
            </Button>
            <Button variant="outline" size="lg" onClick={() => navigate('/signin/mpin')}>
              I already have an account
            </Button>
          </motion.div>

          <motion.ul variants={item} className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
            {ASSURANCES.map((point) => (
              <li key={point} className="flex items-center gap-1.5 text-2xs text-slate">
                <CheckMark className="h-3.5 w-3.5 text-mint-600" strokeWidth={2.5} />
                {point}
              </li>
            ))}
          </motion.ul>
        </motion.div>

        <HeroVisual />
      </Container>
    </section>
  );
}

/**
 * The product itself, with two kinds of depth: it leans after the pointer, and
 * it lifts away as the hero scrolls out. Both run on motion values, so neither
 * re-renders React on every frame.
 */
function HeroVisual() {
  const ref = useRef(null);
  const reduce = useReducedMotion();

  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);
  const x = useSpring(pointerX, { stiffness: 90, damping: 18, mass: 0.6 });
  const y = useSpring(pointerY, { stiffness: 90, damping: 18, mass: 0.6 });

  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] });
  const lift = useTransform(scrollYProgress, [0, 1], [0, reduce ? 0 : -60]);

  useEffect(() => {
    // No cursor to follow on touch screens; the listener would only cost battery.
    const coarse = window.matchMedia?.('(pointer: coarse)').matches;
    if (reduce || coarse) return undefined;

    const onMove = (event) => {
      pointerX.set((event.clientX / window.innerWidth - 0.5) * 28);
      pointerY.set((event.clientY / window.innerHeight - 0.5) * 28);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [reduce, pointerX, pointerY]);

  return (
    // `scale` shrinks what is painted but not the space it reserves, so the
    // negative bottom margins hand back the dead air per breakpoint.
    <motion.div
      ref={ref}
      className="relative -mx-4 mt-4 -mb-40 sm:mx-0 sm:-mb-14 lg:mb-0 lg:mt-0"
      style={{ x, y: lift }}
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.9, ease: EASE, delay: 0.15 }}
    >
      {/* Held at its designed width and centred, so on a phone it scales down
          as one composition instead of being squeezed into the column. */}
      <motion.div style={{ y }} className="flex justify-center max-lg:overflow-x-clip">
        <Showcase className="w-[520px] shrink-0 origin-top scale-[0.72] sm:scale-90 lg:w-full lg:scale-100" />
      </motion.div>
    </motion.div>
  );
}
