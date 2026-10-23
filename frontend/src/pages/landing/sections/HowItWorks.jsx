import { useRef } from 'react';
import { motion, useScroll, useSpring } from 'motion/react';

import { Container, EASE, SectionHeading, VIEWPORT } from './shared';

/* The real onboarding order: RequireAuth in App.jsx walks a new account
   through the first step, and the hub asks for the second before anything
   that moves money. */
const STEPS = [
  {
    title: 'Sign in with your mobile',
    body: 'An OTP to your number, then a 4-digit MPIN for every visit after. There is no password to forget or leak.',
    meta: 'About a minute',
  },
  {
    title: 'Verify yourself and your bank',
    body: 'Complete KYC once, then add your salary account. We deposit ₹1 and match the name your bank holds against your KYC.',
    meta: 'Penny-drop verified',
  },
  {
    title: 'Link your cards and EMIs',
    body: 'Cards are tokenised with your issuer, never stored. Add each loan with its lender, amount and due date.',
    meta: 'RBI Card-on-File',
  },
  {
    title: 'Pay, track, and stop worrying',
    body: 'Every due date in one calendar, reminders before each one, and auto-pay for the EMIs you would rather not think about.',
    meta: 'Notice 48h before any debit',
  },
];

export function HowItWorks() {
  const listRef = useRef(null);
  // The rail fills as the steps pass the middle of the screen, so it tracks
  // the reader instead of animating on its own clock.
  const { scrollYProgress } = useScroll({ target: listRef, offset: ['start 70%', 'end 55%'] });
  const fill = useSpring(scrollYProgress, { stiffness: 120, damping: 30 });

  return (
    <section id="how-it-works" className="py-16 lg:py-24">
      <Container>
        <SectionHeading
          eyebrow="How it works"
          title="From sign-up to sorted in four steps"
          body="No branch visit, no paperwork, no password. The order below is the order the app walks you through."
        />

        <ol ref={listRef} className="relative mx-auto mt-14 max-w-3xl">
          <span aria-hidden="true" className="absolute bottom-6 left-[1.375rem] top-6 w-px bg-line" />
          <motion.span
            aria-hidden="true"
            className="absolute bottom-6 left-[1.375rem] top-6 w-px origin-top bg-mint"
            style={{ scaleY: fill }}
          />

          {STEPS.map((step, index) => (
            <motion.li
              key={step.title}
              className="relative flex gap-5 pb-10 last:pb-0 sm:gap-7"
              initial={{ opacity: 0, x: -12 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={VIEWPORT}
              transition={{ duration: 0.6, ease: EASE, delay: 0.05 }}
            >
              <span className="money relative z-10 grid h-11 w-11 shrink-0 place-items-center rounded-full border border-line bg-canvas text-sm font-bold text-ink shadow-card">
                {String(index + 1).padStart(2, '0')}
              </span>

              <div className="min-w-0 flex-1 rounded-2xl border border-line bg-canvas p-5 transition-all duration-base ease-glide hover:-translate-y-0.5 hover:shadow-card">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h3 className="text-base font-bold text-ink">{step.title}</h3>
                  <span className="text-2xs font-semibold uppercase tracking-[0.12em] text-mint-800">
                    {step.meta}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-slate">{step.body}</p>
              </div>
            </motion.li>
          ))}
        </ol>
      </Container>
    </section>
  );
}
