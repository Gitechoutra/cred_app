import { useId, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';

import { IconHelp } from '../../../components/layout/AppShell';
import { cx } from '../../../components/ui';
import { Container, EASE, FadeIn, SectionHeading } from './shared';

const QUESTIONS = [
  {
    q: 'Is CashU a bank?',
    a: 'No. CashU is a technology platform that works with licensed payment and lending partners. It does not take deposits or hold your money, and every payment settles through a regulated partner.',
  },
  {
    q: 'Do you store my card number?',
    a: 'Never. Card details are tokenised with your issuer under RBI Card-on-File rules. We keep a network token and the last four digits, which is enough to show and pay the card, and useless to anyone who steals it.',
  },
  {
    q: 'What does it cost?',
    a: 'Linking cards, tracking EMIs and getting reminders is free. Some payments, such as Pay Bills, carry a convenience fee plus GST. The exact amount is shown before you confirm, never added afterwards.',
  },
  {
    q: 'How is my CashU credit limit decided?',
    a: 'From your salary and your credit bureau score, checked when you apply. You will see the decision and the limit in the app, and you can follow the application while it is reviewed.',
  },
  {
    q: 'Can I stop an auto-pay once it is set up?',
    a: 'Yes. You get notice 48 hours before every debit, and you can pause or cancel the mandate from the EMI screen up to a day before the due date.',
  },
  {
    q: 'I work at CashU. Where do I sign in?',
    a: 'Use Admin login in the top bar. Staff accounts are issued by CashU, sign in through a separate door, and every action in the operations console is audited.',
  },
];

export function Faq() {
  // One open at a time: an FAQ with four answers expanded is just a wall of text.
  const [open, setOpen] = useState(0);

  return (
    <section id="faq" className="py-16 lg:py-24">
      <Container>
        <SectionHeading eyebrow="FAQ" icon={IconHelp} title="Questions people ask before signing up" />

        <FadeIn className="mx-auto mt-12 max-w-3xl divide-y divide-line overflow-hidden rounded-3xl border border-line bg-canvas shadow-card">
          {QUESTIONS.map((item, index) => (
            <FaqItem
              key={item.q}
              item={item}
              open={open === index}
              onToggle={() => setOpen(open === index ? -1 : index)}
            />
          ))}
        </FadeIn>
      </Container>
    </section>
  );
}

function FaqItem({ item, open, onToggle }) {
  const id = useId();

  return (
    <div>
      <h3>
        <button
          type="button"
          id={`${id}-q`}
          aria-expanded={open}
          aria-controls={`${id}-a`}
          onClick={onToggle}
          className="flex w-full items-center justify-between gap-4 px-5 py-5 text-left transition-colors duration-base hover:bg-mist/60 sm:px-6"
        >
          <span className="text-sm font-semibold text-ink sm:text-base">{item.q}</span>
          <span
            aria-hidden="true"
            className={cx(
              'relative grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors duration-base',
              open ? 'bg-mint text-ink' : 'bg-mist text-slate',
            )}
          >
            <span className="absolute h-0.5 w-3 rounded bg-current" />
            <span
              className={cx(
                'absolute h-3 w-0.5 rounded bg-current transition-transform duration-base ease-glide',
                open && 'scale-y-0',
              )}
            />
          </span>
        </button>
      </h3>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="answer"
            id={`${id}-a`}
            role="region"
            aria-labelledby={`${id}-q`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.32, ease: EASE }}
            className="overflow-hidden"
          >
            <p className="px-5 pb-5 text-sm leading-relaxed text-slate sm:px-6">{item.a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
