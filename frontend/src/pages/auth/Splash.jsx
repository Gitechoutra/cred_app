import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/ui';

/**
 * The first screen.
 *
 * One promise, one action. Everything a fintech landing page usually shouts
 * about - features, security badges, app-store buttons - is noise before the
 * user has any reason to care.
 */
export default function Splash() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-6">
        <div className="flex flex-1 flex-col justify-center py-12">
          <Logo className="h-14 w-14 animate-scale-in" />

          <h1 className="mt-8 text-[2.5rem] font-bold leading-[1.1] tracking-tight text-ink animate-fade-up">
            Every card.
            <br />
            Every EMI.
            <br />
            <span className="relative inline-block">
              One view.
              <span
                className="absolute -bottom-1 left-0 h-3 w-full -skew-x-6 bg-mint/35"
                aria-hidden="true"
              />
            </span>
          </h1>

          <p
            className="mt-5 max-w-xs text-[15px] leading-relaxed text-slate animate-fade-up"
            style={{ animationDelay: '80ms' }}
          >
            Track what you owe across every credit card and loan, pay it without
            hunting for six different portals, and move credit to your bank when
            you need it.
          </p>

          <ul className="mt-8 space-y-3.5 animate-fade-up" style={{ animationDelay: '160ms' }}>
            <Feature text="Bank-grade tokenised card linking" />
            <Feature text="Automatic EMI reminders and auto-pay" />
            <Feature text="Transparent fees, disclosed upfront" />
          </ul>
        </div>

        <div
          className="space-y-3 pb-10 animate-fade-up"
          style={{ animationDelay: '240ms' }}
        >
          <Button variant="mint" size="lg" full onClick={() => navigate('/signin')}>
            Get started
          </Button>

          <Button variant="ghost" size="lg" full onClick={() => navigate('/signin/mpin')}>
            I already have an account
          </Button>

          <p className="pt-2 text-center text-2xs leading-relaxed text-slate-light">
            By continuing you agree to our Terms of Service and Privacy Policy.
            CashU never stores your card number, CVV or PIN.
          </p>
        </div>
      </div>
    </div>
  );
}

function Feature({ text }) {
  return (
    <li className="flex items-center gap-3">
      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-mint">
        <svg viewBox="0 0 20 20" className="h-3 w-3 text-ink" fill="none">
          <path
            d="M5 10.5l3.5 3.5L15 7"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="text-sm text-ink">{text}</span>
    </li>
  );
}

export function Logo({ className = 'h-10 w-10' }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label="CashU">
      <rect width="64" height="64" rx="16" fill="#0A0F0D" />
      <path
        d="M20 18v16a12 12 0 0 0 24 0V18"
        fill="none"
        stroke="#00F5B8"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <path
        d="M32 40V22l7 7"
        fill="none"
        stroke="#00F5B8"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
    </svg>
  );
}
