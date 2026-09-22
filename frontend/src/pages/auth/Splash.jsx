import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Logo } from '../../components/layout/AppShell';
import Showcase, { CreditCard } from '../../components/marketing/Showcase';
import { Button, cx } from '../../components/ui';
import { Reveal, useCountUp, useParallax } from '../../hooks/useReveal';

/**
 * Landing page.
 *
 * White canvas, one mint accent, and a product visual that is the actual
 * product rather than a stock illustration.
 *
 * The motion rule: everything arrives once and then settles. The only things
 * that keep moving are the background orbs and the issuer marquee, both far
 * enough below the content to read as atmosphere. A page that fidgets reads as
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
        <Stats />
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

const NAV_LINKS = [
  { label: 'How it works', id: 'features' },
  { label: 'Security', id: 'security' },
  { label: 'Sign in', id: 'login' },
];

function TopBar({ onUser, onAdmin }) {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // An open menu over a scrolling page is disorienting, and on iOS the body
  // scrolls behind the overlay rather than the overlay itself.
  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [menuOpen]);

  return (
    <header
      className={cx(
        'sticky top-0 z-50 transition-all duration-slow ease-glide',
        scrolled
          ? 'border-b border-line bg-canvas/80 shadow-card backdrop-blur-xl'
          : 'border-b border-transparent bg-canvas/60 backdrop-blur-sm',
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
          {NAV_LINKS.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="group relative rounded-lg px-3 py-2 text-xs font-medium text-slate transition-colors duration-base hover:text-ink"
            >
              {item.label}
              {/* An underline that grows from the centre, rather than a
                  background that blinks on. */}
              <span
                aria-hidden="true"
                className="absolute inset-x-3 bottom-1 h-px origin-center scale-x-0 bg-mint transition-transform duration-base ease-glide group-hover:scale-x-100"
              />
            </a>
          ))}
        </nav>

        <button
          type="button"
          onClick={onAdmin}
          className="hidden rounded-xl border border-line px-3.5 py-2 text-xs font-semibold text-slate transition-all duration-base ease-glide hover:-translate-y-px hover:border-ink/20 hover:text-ink sm:block"
        >
          Admin login
        </button>

        <div className="hidden sm:block">
          <Button variant="mint" size="sm" onClick={onUser}>
            User login
          </Button>
        </div>

        {/* Below `sm` both doors move into the sheet, so the bar keeps its
            shape at 320px instead of wrapping onto two lines. */}
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
          className="grid h-10 w-10 place-items-center rounded-xl border border-line text-ink transition-colors duration-base hover:bg-mist sm:hidden"
        >
          <span className="relative block h-4 w-5">
            {/* Three bars that become a cross - the same elements moving,
                not one icon swapped for another. */}
            <span
              className={cx(
                'absolute left-0 block h-0.5 w-5 rounded bg-current transition-all duration-base ease-glide',
                menuOpen ? 'top-1/2 -translate-y-1/2 rotate-45' : 'top-0',
              )}
            />
            <span
              className={cx(
                'absolute left-0 top-1/2 block h-0.5 w-5 -translate-y-1/2 rounded bg-current transition-all duration-base ease-glide',
                menuOpen && 'scale-x-0 opacity-0',
              )}
            />
            <span
              className={cx(
                'absolute left-0 block h-0.5 w-5 rounded bg-current transition-all duration-base ease-glide',
                menuOpen ? 'top-1/2 -translate-y-1/2 -rotate-45' : 'bottom-0',
              )}
            />
          </span>
        </button>
      </div>

      {/* Mobile sheet */}
      {menuOpen && (
        <div className="sm:hidden">
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
            className="fixed inset-0 top-[4.25rem] z-40 cursor-default bg-ink/20 backdrop-blur-sm"
          />
          <div className="relative z-50 animate-slide-down border-t border-line bg-canvas px-4 pb-5 pt-3 shadow-lift">
            <div className="stagger space-y-1">
              {NAV_LINKS.map((item) => (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-xl px-3 py-3 text-sm font-medium text-ink transition-colors duration-base hover:bg-mist"
                >
                  {item.label}
                </a>
              ))}
            </div>

            <div className="mt-4 space-y-2 border-t border-line pt-4">
              <Button variant="mint" size="lg" full onClick={onUser}>
                User login
              </Button>
              <Button variant="outline" size="lg" full onClick={onAdmin}>
                Admin login
              </Button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}

/* ── Hero ───────────────────────────────────────────────────────────────── */

function Hero({ navigate }) {
  // One pointer listener, two layers reading it at different depths - which is
  // what sells the parallax as depth rather than as a slide.
  const drift = useParallax({ strength: 14 });

  return (
    <section className="relative isolate">
      {/* Atmosphere. Sits behind everything, never takes a pointer event. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <span className="orb animate-drift -left-24 -top-32 h-[26rem] w-[26rem] bg-mint/30" />
        <span className="orb animate-drift-slow right-[-8rem] top-10 h-[22rem] w-[22rem] bg-mint-300/25" />
        <span className="orb animate-drift-slow bottom-[-10rem] left-1/3 h-[20rem] w-[20rem] bg-mint-200/30" />
      </div>

      <div className="mx-auto grid w-full max-w-6xl items-center gap-4 px-4 pb-8 pt-10 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:gap-8 lg:px-8 lg:pb-20 lg:pt-16">
        <div>
          <span
            className="inline-flex animate-fade-up items-center gap-2 rounded-full border border-mint-200 bg-mint-50/80 px-3 py-1.5 text-2xs font-semibold text-mint-800 backdrop-blur"
            style={{ animationDelay: '40ms' }}
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-mint-600" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-mint-600" />
            </span>
            RBI-compliant card tokenisation
          </span>

          {/* Each line is clipped by its own wrapper, so the text rises from
              behind its baseline instead of fading in. */}
          <h1 className="mt-6 text-[2.75rem] font-bold leading-[1.05] tracking-[-0.02em] text-ink sm:text-[3.5rem] lg:text-[4rem]">
            <span className="line-clip">
              <span style={{ animationDelay: '120ms' }}>Every card.</span>
            </span>
            <span className="line-clip">
              <span style={{ animationDelay: '200ms' }}>Every EMI.</span>
            </span>
            <span className="line-clip">
              <span style={{ animationDelay: '280ms' }}>
                <span className="relative inline-block">
                  <span className="relative z-10">One view.</span>
                  <span
                    aria-hidden="true"
                    className="absolute -bottom-1 left-0 h-4 w-full -skew-x-6 rounded-sm bg-mint/35"
                  />
                </span>
              </span>
            </span>
          </h1>

          <p
            className="mt-6 max-w-lg animate-fade-up text-base leading-relaxed text-slate sm:text-lg"
            style={{ animationDelay: '380ms' }}
          >
            Track what you owe across every credit card and loan, pay it without
            hunting through six different portals, and turn credit headroom into
            bank liquidity — with the fee shown before you authorise.
          </p>

          <div
            className="mt-8 flex animate-fade-up flex-wrap gap-3"
            style={{ animationDelay: '440ms' }}
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
            style={{ animationDelay: '500ms' }}
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
        <div
          className="relative -mx-4 mt-4 -mb-40 sm:mx-0 sm:-mb-14 lg:mb-0 lg:mt-0"
          style={{
            transform: `translate3d(${drift.x}px, ${drift.y}px, 0)`,
            transition: 'transform 400ms cubic-bezier(0.16,1,0.3,1)',
          }}
        >
          <Showcase className="origin-top scale-[0.72] sm:scale-90 lg:scale-100" />
        </div>
      </div>
    </section>
  );
}

/* ── Stats ──────────────────────────────────────────────────────────────── */

/* Every figure here is a property of the product, not a growth claim. A
   landing page inventing user counts is the fastest way to lose the trust this
   page exists to build. */
const STATS = [
  { value: 48, suffix: 'h', label: 'Notice before any auto-debit', hint: 'RBI asks for 24' },
  { value: 0, suffix: '', label: 'Card numbers stored', hint: 'Tokenised, never held' },
  { value: 100, suffix: '%', label: 'Ledger re-verified nightly', hint: 'Double-entry, append-only' },
  { value: 1, prefix: '₹', suffix: '', label: 'Penny-drop name check', hint: 'Before any payout' },
];

function Stats() {
  return (
    <section className="mx-auto w-full max-w-6xl px-4 pb-4 pt-8 sm:px-6 lg:px-8 lg:pt-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {STATS.map((stat, index) => (
          <Reveal key={stat.label} delay={index * 70}>
            <StatCard {...stat} />
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function StatCard({ value, prefix = '', suffix = '', label, hint }) {
  const { ref, value: counted } = useCountUp(value);

  return (
    <div
      ref={ref}
      className="group edge-glow relative h-full overflow-hidden rounded-2xl border border-line bg-canvas p-5 transition-all duration-base ease-glide hover:-translate-y-1 hover:shadow-lift"
    >
      <span aria-hidden="true" className="shine absolute inset-0" />

      <p className="money relative text-3xl font-bold tracking-tight text-ink">
        {prefix}
        {Math.round(counted)}
        {suffix}
      </p>
      <p className="relative mt-1.5 text-xs font-semibold text-ink">{label}</p>
      <p className="relative mt-1 text-2xs text-slate">{hint}</p>
    </div>
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
    <section className="mt-10 border-y border-line bg-mist/50 py-8">
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
      <Reveal>
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
      </Reveal>

      <div className="mx-auto mt-10 grid max-w-4xl gap-5 md:grid-cols-2">
        <Reveal delay={80}>
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
        </Reveal>

        <Reveal delay={160}>
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
        </Reveal>
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
        'group edge-glow relative flex h-full w-full flex-col overflow-hidden rounded-3xl border p-7 text-left',
        'transition-all duration-slow ease-glide hover:-translate-y-1.5 hover:shadow-lift active:translate-y-0',
        primary ? 'border-mint-200 bg-mint-50' : 'border-line bg-canvas hover:border-ink/20',
      )}
    >
      <span aria-hidden="true" className="shine absolute inset-0" />

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

        <ul className="mt-5 space-y-2.5">
          {points.map((point) => (
            <li key={point} className="flex items-start gap-2.5 text-sm text-ink">
              <span
                className={cx(
                  'mt-1 grid h-4 w-4 shrink-0 place-items-center rounded-full transition-transform duration-base ease-glide group-hover:scale-110',
                  primary ? 'bg-mint text-ink' : 'bg-ink text-mint',
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
              <span className="leading-snug">{point}</span>
            </li>
          ))}
        </ul>

        <span
          className={cx(
            'mt-7 inline-flex items-center gap-2 text-sm font-bold transition-all duration-base ease-glide group-hover:gap-3',
            primary ? 'text-mint-800' : 'text-ink',
          )}
        >
          {cta}
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
            <path
              d="M4 10h11M11 5l5 5-5 5"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>

        <span className="mt-3.5 block text-2xs leading-relaxed text-slate">{footnote}</span>
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
    <section id="features" className="relative border-t border-line bg-mist/40 py-16 lg:py-24">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <span className="orb animate-drift-slow -right-32 top-20 h-80 w-80 bg-mint/15" />
      </div>

      <div className="relative mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
        <Reveal>
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-bold tracking-tight text-ink sm:text-4xl">
              Built for the way Indian credit actually works
            </h2>
            <p className="mt-3 text-base text-slate">
              Four things, done properly, instead of forty done partly.
            </p>
          </div>
        </Reveal>

        <div className="mt-12 grid gap-5 md:grid-cols-2">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.step} delay={index * 80}>
              <article className="group edge-glow relative h-full overflow-hidden rounded-2xl border border-line bg-canvas/80 p-6 backdrop-blur transition-all duration-slow ease-glide hover:-translate-y-1 hover:shadow-lift">
                <span aria-hidden="true" className="shine absolute inset-0" />

                <div className="relative flex items-start gap-4">
                  <span className="money grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-ink text-sm font-bold text-mint transition-all duration-base ease-glide group-hover:scale-110 group-hover:bg-mint group-hover:text-ink group-hover:shadow-mint">
                    {feature.step}
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-base font-bold text-ink">{feature.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-slate">{feature.body}</p>
                  </div>
                </div>
              </article>
            </Reveal>
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
        <Reveal>
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
        </Reveal>

        <div className="space-y-4">
          {GUARANTEES.map((item, index) => (
            <Reveal key={item.title} delay={index * 70}>
              <div className="group edge-glow relative overflow-hidden rounded-2xl border border-line bg-canvas p-5 transition-all duration-base ease-glide hover:-translate-y-0.5 hover:shadow-card">
                <span aria-hidden="true" className="shine absolute inset-0" />

                <div className="relative flex items-start gap-3.5">
                  <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-mint text-ink transition-transform duration-base ease-glide group-hover:scale-110">
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
            </Reveal>
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
      <Reveal>
        <div
          className={cx(
            'mesh relative overflow-hidden rounded-3xl px-6 py-14 text-center sm:px-12',
            'bg-[linear-gradient(120deg,#0A0F0D_0%,#14211D_38%,#00312a_62%,#0A0F0D_100%)]',
          )}
        >
          <span
            aria-hidden="true"
            className="orb animate-drift -left-20 -top-20 h-64 w-64 bg-mint/30"
          />
          <span
            aria-hidden="true"
            className="orb animate-drift-slow -bottom-24 -right-16 h-64 w-64 bg-mint/25"
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
      </Reveal>
    </section>
  );
}

/* ── Footer ─────────────────────────────────────────────────────────────── */

function Footer({ navigate }) {
  return (
    <footer className="border-t border-line bg-mist">
      <div className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <Logo className="h-8 w-8" />
              <p className="text-base font-bold tracking-tight text-ink">CashU</p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate">
              Your credit cards and EMIs, under one glass pane.
            </p>
          </div>

          <FooterColumn title="Sign in">
            <FooterAction onClick={() => navigate('/signin')} strong>
              User login
            </FooterAction>
            <FooterAction onClick={() => navigate('/admin/login')}>Admin login</FooterAction>
          </FooterColumn>

          <FooterColumn title="Product">
            <FooterLink href="#features">How it works</FooterLink>
            <FooterLink href="#security">Security</FooterLink>
            <FooterLink href="#login">Choose your door</FooterLink>
          </FooterColumn>

          <FooterColumn title="Support">
            {/* Support lives behind the member app, so these route into it
                rather than pointing at pages that do not exist. */}
            <FooterAction onClick={() => navigate('/signin')}>Help &amp; support</FooterAction>
            <FooterAction onClick={() => navigate('/signin')}>Raise a request</FooterAction>
          </FooterColumn>
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

function FooterColumn({ title, children }) {
  return (
    <div>
      <p className="text-2xs font-bold uppercase tracking-[0.14em] text-slate">{title}</p>
      <div className="mt-3 space-y-2">{children}</div>
    </div>
  );
}

function FooterAction({ onClick, strong, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'block text-sm transition-colors duration-base hover:text-ink hover:underline',
        strong ? 'font-semibold text-ink' : 'font-medium text-slate',
      )}
    >
      {children}
    </button>
  );
}

function FooterLink({ href, children }) {
  return (
    <a
      href={href}
      className="block text-sm font-medium text-slate transition-colors duration-base hover:text-ink hover:underline"
    >
      {children}
    </a>
  );
}
