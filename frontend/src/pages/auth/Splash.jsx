import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Logo } from '../../components/layout/AppShell';
import Showcase, { CreditCard } from '../../components/marketing/Showcase';
import { Button, cx } from '../../components/ui';

/**
 * Landing page.
 *
 * White canvas, one mint accent, and a product visual that is the actual
 * product rather than a stock illustration. Motion is used once per element —
 * things arrive, then settle — because a page that keeps moving reads as
 * unserious, and this one is asking people to trust it with credit cards.
 *
 * Both doors are reachable from the top bar, the hero, a dedicated section and
 * the footer: the two roles have genuinely different needs and the page never
 * makes someone guess which one they are.
 */
export default function Splash() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen overflow-x-hidden bg-canvas">
      <TopBar onUser={() => navigate('/signin')} onAdmin={() => navigate('/admin/login')} />

      <main>
        <Hero navigate={navigate} />
        <TrustStrip />
        <Doors navigate={navigate} />
        <Features />
        <Security />
        <CallToAction navigate={navigate} />
      </main>

      <Footer navigate={navigate} />
    </div>
  );
}

/* ── Top bar ────────────────────────────────────────────────────────────── */

function TopBar({ onUser, onAdmin }) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <header
      className={cx(
        'sticky top-0 z-50 bg-canvas/85 backdrop-blur transition-shadow duration-300',
        scrolled ? 'border-b border-line shadow-card' : 'border-b border-transparent',
      )}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3.5 sm:px-6 lg:px-8">
        <div className="flex flex-1 items-center gap-2.5">
          <Logo className="h-9 w-9" />
          <div>
            <p className="text-base font-bold leading-none tracking-tight text-ink">CashU</p>
            <p className="mt-1 hidden text-2xs text-slate sm:block">Credit &amp; EMI hub</p>
          </div>
        </div>

        <nav className="mr-2 hidden items-center gap-1 md:flex">
          {[
            { label: 'How it works', id: 'features' },
            { label: 'Security', id: 'security' },
          ].map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="rounded-lg px-3 py-2 text-xs font-medium text-slate transition hover:bg-mist hover:text-ink"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <button
          type="button"
          onClick={onAdmin}
          className="rounded-xl border border-line px-3.5 py-2 text-xs font-semibold text-slate transition hover:border-ink/20 hover:text-ink"
        >
          Admin login
        </button>

        <Button variant="mint" size="sm" onClick={onUser}>
          User login
        </Button>
      </div>
    </header>
  );
}

/* ── Hero ───────────────────────────────────────────────────────────────── */

function Hero({ navigate }) {
  return (
    <section className="relative">
      <div className="mx-auto grid w-full max-w-6xl items-center gap-4 px-4 pb-8 pt-10 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:gap-8 lg:px-8 lg:pb-20 lg:pt-16">
        <div>
          <span
            className="inline-flex animate-fade-up items-center gap-2 rounded-full border border-mint-200 bg-mint-50 px-3 py-1.5 text-2xs font-semibold text-mint-800"
            style={{ animationDelay: '40ms' }}
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-mint-600" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-mint-600" />
            </span>
            RBI-compliant card tokenisation
          </span>

          <h1
            className="mt-6 animate-fade-up text-[2.75rem] font-bold leading-[1.05] tracking-[-0.02em] text-ink sm:text-[3.5rem] lg:text-[4rem]"
            style={{ animationDelay: '100ms' }}
          >
            Every card.
            <br />
            Every EMI.
            <br />
            <span className="relative inline-block">
              <span className="relative z-10">One view.</span>
              <span
                aria-hidden="true"
                className="absolute -bottom-1 left-0 h-4 w-full -skew-x-6 rounded-sm bg-mint/35"
              />
            </span>
          </h1>

          <p
            className="mt-6 max-w-lg animate-fade-up text-base leading-relaxed text-slate sm:text-lg"
            style={{ animationDelay: '160ms' }}
          >
            Track what you owe across every credit card and loan, pay it without
            hunting through six different portals, and turn credit headroom into
            bank liquidity — with the fee shown before you authorise.
          </p>

          <div
            className="mt-8 flex animate-fade-up flex-wrap gap-3"
            style={{ animationDelay: '220ms' }}
          >
            <Button variant="mint" size="lg" onClick={() => navigate('/signin')}>
              Get started — it&rsquo;s free
              <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
                <path
                  d="M4 10h11M11 5l5 5-5 5"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </Button>
            <Button variant="outline" size="lg" onClick={() => navigate('/signin/mpin')}>
              I already have an account
            </Button>
          </div>

          <div
            className="mt-8 flex animate-fade-up flex-wrap items-center gap-x-6 gap-y-2"
            style={{ animationDelay: '280ms' }}
          >
            {['No password to remember', 'Zero card data stored', 'Free to use'].map(
              (point) => (
                <span key={point} className="flex items-center gap-1.5 text-2xs text-slate">
                  <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 text-mint-600" fill="none">
                    <path
                      d="M5 10.5l3.5 3.5L15 7"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {point}
                </span>
              ),
            )}
          </div>
        </div>

        {/* The product itself, scaled down on smaller screens.
            `scale` shrinks what is painted but not the space it reserves, so a
            0.72 scale on a 560px block would leave ~157px of dead air beneath
            it. The negative margins reclaim exactly that, per breakpoint. */}
        <div className="relative -mx-4 mt-4 -mb-40 sm:mx-0 sm:-mb-14 lg:mb-0 lg:mt-0">
          <Showcase className="origin-top scale-[0.72] sm:scale-90 lg:scale-100" />
        </div>
      </div>
    </section>
  );
}

/* ── Trust strip ────────────────────────────────────────────────────────── */

const ISSUERS = [
  'HDFC Bank', 'ICICI Bank', 'State Bank of India', 'Axis Bank',
  'Kotak Mahindra', 'IndusInd Bank', 'IDFC FIRST', 'Bajaj Finserv',
  'HDB Financial', 'Yes Bank', 'RBL Bank', 'American Express',
];

function TrustStrip() {
  return (
    <section className="border-y border-line bg-mist/50 py-8">
      <p className="text-center text-2xs font-semibold uppercase tracking-[0.18em] text-slate">
        Works with the cards and lenders you already have
      </p>

      {/* Two copies so the marquee loops seamlessly at -50%. */}
      <div className="relative mt-5 overflow-hidden">
        <div className="flex w-max animate-marquee gap-10">
          {[...ISSUERS, ...ISSUERS].map((issuer, index) => (
            <span
              key={`${issuer}-${index}`}
              className="whitespace-nowrap text-sm font-semibold text-slate-light"
            >
              {issuer}
            </span>
          ))}
        </div>

        {/* Fade the ends so the loop has no visible seam. */}
        <span className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-mist/90 to-transparent" />
        <span className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-mist/90 to-transparent" />
      </div>
    </section>
  );
}

/* ── The two doors ──────────────────────────────────────────────────────── */

function Doors({ navigate }) {
  return (
    <section id="login" className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:px-8 lg:py-24">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-bold tracking-tight text-ink sm:text-4xl">
          Two entrances. Pick yours.
        </h2>
        <p className="mt-3 text-base text-slate">
          CashU keeps customers and staff completely separate. A member account
          can&rsquo;t open the operations console, and a staff account
          doesn&rsquo;t sign in through the customer door.
        </p>
      </div>

      <div className="mx-auto mt-10 grid max-w-4xl gap-5 md:grid-cols-2">
        <Door
          primary
          eyebrow="For customers"
          title="User login"
          description="You have credit cards or loan EMIs you want to manage in one place."
          points={[
            'Sign in with your mobile number and an OTP',
            'Link cards, track limits and due dates',
            'Pay EMIs and transfer credit to your bank',
          ]}
          cta="Continue as user"
          onClick={() => navigate('/signin')}
          footnote="New here? The same button creates your account."
        />

        <Door
          eyebrow="For CashU staff"
          title="Admin login"
          description="You work at CashU and need the operations console."
          points={[
            'Review and approve KYC submissions',
            'Resolve stuck transfers and reversals',
            'Monitor reconciliation and ledger integrity',
          ]}
          cta="Continue as admin"
          onClick={() => navigate('/admin/login')}
          footnote="Requires a staff account. Every action is audited."
        />
      </div>

      <p className="mx-auto mt-7 max-w-xl text-center text-xs leading-relaxed text-slate">
        Not sure which you need? If nobody at CashU gave you a staff account,
        you&rsquo;re a user — take the green door.
      </p>
    </section>
  );
}

function Door({ primary, eyebrow, title, description, points, cta, onClick, footnote }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'group relative flex flex-col overflow-hidden rounded-3xl border p-7 text-left',
        'transition-all duration-300 hover:-translate-y-1 hover:shadow-lift active:translate-y-0',
        primary ? 'border-mint-200 bg-mint-50' : 'border-line bg-canvas hover:border-ink/20',
      )}
    >
      {primary && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-mint/25 blur-3xl transition-opacity duration-300 group-hover:opacity-70"
        />
      )}

      <div className="relative">
        <span
          className={cx(
            'text-2xs font-bold uppercase tracking-[0.14em]',
            primary ? 'text-mint-800' : 'text-slate',
          )}
        >
          {eyebrow}
        </span>

        <h3 className="mt-2.5 text-2xl font-bold tracking-tight text-ink">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate">{description}</p>

        <ul className="mt-6 space-y-3">
          {points.map((point) => (
            <li key={point} className="flex items-start gap-3">
              <span
                className={cx(
                  'mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full',
                  primary ? 'bg-mint text-ink' : 'bg-mist text-slate',
                )}
              >
                <svg viewBox="0 0 20 20" className="h-2.5 w-2.5" fill="none">
                  <path
                    d="M5 10.5l3.5 3.5L15 7"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <span className="text-sm leading-relaxed text-ink/75">{point}</span>
            </li>
          ))}
        </ul>

        <span
          className={cx(
            'mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition',
            primary
              ? 'bg-mint text-ink shadow-mint group-hover:bg-mint-400'
              : 'bg-ink text-white group-hover:bg-ink-800',
          )}
        >
          {cta}
          <svg
            viewBox="0 0 20 20"
            className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
            fill="none"
          >
            <path
              d="M4 10h11M11 5l5 5-5 5"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>

        {footnote && (
          <span className="mt-3.5 block text-2xs leading-relaxed text-slate">{footnote}</span>
        )}
      </div>
    </button>
  );
}

/* ── Features ───────────────────────────────────────────────────────────── */

const FEATURES = [
  {
    step: '01',
    title: 'Link your cards in seconds',
    body: 'Enter your card once and it is tokenised with your issuer under RBI Card-on-File rules. We identify your bank from the first six digits and paint the card in its own brand colours.',
  },
  {
    step: '02',
    title: 'See every due date at once',
    body: 'Cards from HDFC, ICICI, SBI or Axis and loans from Bajaj, HDB or IDFC — one calendar, with reminders seven days and one day before each payment.',
  },
  {
    step: '03',
    title: 'Pay without leaving the app',
    body: 'Settle an EMI over UPI, netbanking or debit card, or arm an NPCI auto-pay mandate and let it handle itself — with notice 48 hours before every debit.',
  },
  {
    step: '04',
    title: 'Turn credit into cash',
    body: 'Move headroom from an eligible card to your own verified bank account by IMPS. The convenience fee and GST are shown before you authorise, never after.',
  },
];

function Features() {
  return (
    <section id="features" className="border-t border-line bg-mist/40 py-16 lg:py-24">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-ink sm:text-4xl">
            Built for the way Indian credit actually works
          </h2>
          <p className="mt-3 text-base text-slate">
            Four things, done properly, instead of forty done partly.
          </p>
        </div>

        <div className="mt-12 grid gap-5 md:grid-cols-2">
          {FEATURES.map((feature) => (
            <article
              key={feature.step}
              className="group rounded-2xl border border-line bg-canvas p-6 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-card"
            >
              <div className="flex items-start gap-4">
                <span className="money grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-ink text-sm font-bold text-mint transition-colors duration-300 group-hover:bg-mint group-hover:text-ink">
                  {feature.step}
                </span>
                <div className="min-w-0">
                  <h3 className="text-base font-bold text-ink">{feature.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate">{feature.body}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Security ───────────────────────────────────────────────────────────── */

const GUARANTEES = [
  {
    title: 'Your card number never reaches us',
    body: 'Card details go from your browser straight to a licensed tokenisation partner. CashU stores a network token and the last four digits — never the full number, the CVV or the PIN.',
  },
  {
    title: 'Money only moves to your own account',
    body: 'Every payout destination is verified by depositing ₹1 and matching the name your bank holds against your KYC record. Third-party transfers are refused outright.',
  },
  {
    title: 'Nothing is debited without warning',
    body: 'Auto-pay sends notice 48 hours before every debit — more than the 24 hours RBI requires — and you can pause or cancel any mandate up to a day beforehand.',
  },
  {
    title: 'Every rupee is auditable',
    body: 'Each movement is recorded as a double-entry journal that is never edited or deleted. Corrections are posted as new entries, and the whole ledger is re-verified nightly.',
  },
];

function Security() {
  return (
    <section id="security" className="py-16 lg:py-24">
      <div className="mx-auto grid w-full max-w-6xl gap-12 px-4 sm:px-6 lg:grid-cols-2 lg:items-center lg:px-8">
        <div>
          <span className="inline-flex items-center gap-2 rounded-full border border-line bg-mist px-3 py-1.5 text-2xs font-bold uppercase tracking-[0.14em] text-slate">
            <svg
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5 text-mint-600"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6z" strokeLinejoin="round" />
              <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Security
          </span>

          <h2 className="mt-5 text-3xl font-bold tracking-tight text-ink sm:text-4xl">
            Four promises we designed the product around
          </h2>
          <p className="mt-4 text-base leading-relaxed text-slate">
            These are not policies written after the fact. Each one is enforced
            in the code — a credit card cannot pay a loan EMI because that option
            does not exist in the system, not because a check happens to catch it.
          </p>

          {/* A single card, restated small, to tie the section to the hero. */}
          <div className="mt-9 hidden lg:block">
            <CreditCard
              compact
              label="HDFC Regalia"
              network="visa"
              last4="4821"
              sheen
              gradient="linear-gradient(135deg,#0A0F0D 0%,#14211D 45%,#00614B 100%)"
              className="animate-float"
            />
          </div>
        </div>

        <div className="space-y-4">
          {GUARANTEES.map((item) => (
            <div
              key={item.title}
              className="rounded-2xl border border-line bg-canvas p-5 transition-shadow duration-300 hover:shadow-card"
            >
              <div className="flex items-start gap-3.5">
                <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-mint text-ink">
                  <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none">
                    <path
                      d="M5 10.5l3.5 3.5L15 7"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <div className="min-w-0">
                  <h3 className="text-sm font-bold text-ink">{item.title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate">{item.body}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Closing CTA ────────────────────────────────────────────────────────── */

function CallToAction({ navigate }) {
  return (
    <section className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6 lg:px-8 lg:pb-24">
      <div className="relative overflow-hidden rounded-3xl bg-ink px-6 py-14 text-center sm:px-12">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -left-20 -top-20 h-64 w-64 rounded-full bg-mint/25 blur-3xl"
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-24 -right-16 h-64 w-64 rounded-full bg-mint/20 blur-3xl"
        />

        <div className="relative mx-auto max-w-2xl">
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Put every card and EMI in one place
          </h2>
          <p className="mt-4 text-base leading-relaxed text-white/60">
            Takes about a minute. All you need is your mobile number.
          </p>

          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <Button variant="mint" size="lg" onClick={() => navigate('/signin')}>
              Create your account
            </Button>
            <Button
              variant="ghost"
              size="lg"
              className="text-white/70 hover:bg-white/10 hover:text-white"
              onClick={() => navigate('/admin/login')}
            >
              Staff? Admin login
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Footer ─────────────────────────────────────────────────────────────── */

function Footer({ navigate }) {
  return (
    <footer className="border-t border-line bg-mist">
      <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-start justify-between gap-8">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <Logo className="h-8 w-8" />
              <p className="text-base font-bold tracking-tight text-ink">CashU</p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate">
              Your credit cards and EMIs, under one glass pane.
            </p>
          </div>

          <div>
            <p className="text-2xs font-bold uppercase tracking-[0.14em] text-slate">Sign in</p>
            <div className="mt-3 space-y-2">
              <button
                type="button"
                onClick={() => navigate('/signin')}
                className="block text-sm font-semibold text-ink hover:underline"
              >
                User login
              </button>
              <button
                type="button"
                onClick={() => navigate('/admin/login')}
                className="block text-sm font-medium text-slate transition hover:text-ink hover:underline"
              >
                Admin login
              </button>
            </div>
          </div>

          <div>
            <p className="text-2xs font-bold uppercase tracking-[0.14em] text-slate">Product</p>
            <div className="mt-3 space-y-2">
              {[
                { label: 'How it works', href: '#features' },
                { label: 'Security', href: '#security' },
              ].map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="block text-sm font-medium text-slate transition hover:text-ink hover:underline"
                >
                  {link.label}
                </a>
              ))}
            </div>
          </div>
        </div>

        <p className="mt-10 border-t border-line pt-6 text-2xs leading-relaxed text-slate">
          CashU is a technology platform operating with licensed payment
          partners. It is not a bank, does not issue credit and does not hold
          customer funds. Card tokenisation follows RBI Card-on-File rules;
          personal data is handled under the DPDPA 2023. By continuing you agree
          to our Terms of Service and Privacy Policy.
        </p>
      </div>
    </footer>
  );
}
