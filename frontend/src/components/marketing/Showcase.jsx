import { cx } from '../ui';

/**
 * Hero product visual.
 *
 * A phone running the CashU dashboard with credit cards floating behind it,
 * assembled entirely from markup and CSS — no image assets, so it stays crisp
 * at any density, themes from the same tokens as the app, and costs the bundle
 * nothing.
 *
 * The cards deliberately use real issuer brand colours and a genuine card
 * anatomy (chip, contactless mark, tabular-numeral PAN). A fintech landing page
 * with a generic gradient rectangle reads as a template; getting the details
 * right is most of what makes this feel like a real product.
 */

/* ── Credit card ────────────────────────────────────────────────────────── */

function CreditCard({
  label,
  network,
  last4,
  gradient,
  className,
  style,
  sheen = false,
  compact = false,
}) {
  return (
    <div
      className={cx(
        'relative overflow-hidden rounded-2xl shadow-lift ring-1 ring-white/10',
        compact ? 'aspect-[1.585/1] w-44' : 'aspect-[1.585/1] w-64',
        className,
      )}
      style={{ backgroundImage: gradient, ...style }}
      aria-hidden="true"
    >
      {/* Soft top-light, so a flat gradient reads as a physical surface. */}
      <span className="pointer-events-none absolute -right-10 -top-16 h-44 w-44 rounded-full bg-white/15 blur-2xl" />
      <span className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/30" />

      {/* Travelling highlight. */}
      {sheen && (
        <span className="pointer-events-none absolute inset-y-0 -left-1/3 w-1/3 animate-sheen bg-gradient-to-r from-transparent via-white/25 to-transparent" />
      )}

      <div className={cx('relative flex h-full flex-col justify-between', compact ? 'p-3.5' : 'p-5')}>
        <div className="flex items-start justify-between">
          <p className={cx('font-semibold text-white', compact ? 'text-2xs' : 'text-sm')}>
            {label}
          </p>
          <ContactlessMark className={compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
        </div>

        <div className={cx('flex items-end justify-between', compact ? 'gap-2' : 'gap-3')}>
          <div className="min-w-0">
            <ChipMark className={compact ? 'h-5 w-6' : 'h-7 w-9'} />
            <p
              className={cx(
                'money mt-2 tracking-[0.2em] text-white/80',
                compact ? 'text-[9px]' : 'text-xs',
              )}
            >
              •••• {last4}
            </p>
          </div>

          <NetworkMark network={network} compact={compact} />
        </div>
      </div>
    </div>
  );
}

function ChipMark({ className }) {
  return (
    <svg viewBox="0 0 36 28" className={className} fill="none">
      <rect width="36" height="28" rx="5" fill="url(#chip)" />
      <path
        d="M12 0v28M24 0v28M0 9.5h36M0 18.5h36"
        stroke="rgba(0,0,0,0.22)"
        strokeWidth="1.2"
      />
      <defs>
        <linearGradient id="chip" x1="0" y1="0" x2="36" y2="28">
          <stop stopColor="#F6E7B4" />
          <stop offset="0.5" stopColor="#D9BE7A" />
          <stop offset="1" stopColor="#F2DFA8" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function ContactlessMark({ className }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none">
      {[5, 9, 13].map((radius, index) => (
        <path
          key={radius}
          d={`M${8 - index * 2} ${12 - radius * 0.62}a${radius} ${radius} 0 0 1 0 ${radius * 1.24}`}
          stroke="rgba(255,255,255,0.75)"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}

function NetworkMark({ network, compact }) {
  if (network === 'mastercard') {
    return (
      <span className="flex shrink-0 items-center" aria-hidden="true">
        <span
          className={cx('rounded-full bg-[#EB001B]/90', compact ? 'h-4 w-4' : 'h-6 w-6')}
        />
        <span
          className={cx(
            '-ml-1.5 rounded-full bg-[#F79E1B]/90 mix-blend-screen',
            compact ? 'h-4 w-4' : 'h-6 w-6',
          )}
        />
      </span>
    );
  }

  if (network === 'rupay') {
    return (
      <span
        className={cx(
          'shrink-0 font-bold italic tracking-tight text-white/90',
          compact ? 'text-[9px]' : 'text-xs',
        )}
      >
        RuPay
      </span>
    );
  }

  return (
    <span
      className={cx(
        'shrink-0 font-bold italic tracking-tight text-white/90',
        compact ? 'text-[10px]' : 'text-sm',
      )}
    >
      VISA
    </span>
  );
}

/* ── Phone ──────────────────────────────────────────────────────────────── */

function Phone({ className, style }) {
  return (
    <div className={cx('relative', className)} style={style}>
      {/* Device body */}
      <div className="relative w-[264px] rounded-[2.5rem] bg-ink p-2.5 shadow-lift ring-1 ring-ink/10">
        {/* Screen */}
        <div className="relative overflow-hidden rounded-[2rem] bg-canvas">
          {/* Dynamic island */}
          <div className="absolute left-1/2 top-2 z-20 h-5 w-20 -translate-x-1/2 rounded-full bg-ink" />

          <div className="h-[520px] overflow-hidden px-3.5 pb-3.5 pt-9">
            {/* Status row */}
            <div className="mb-3 flex items-center justify-between px-1">
              <span className="money text-[9px] font-semibold text-ink">9:41</span>
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-ink/30" />
                <span className="h-1.5 w-1.5 rounded-full bg-ink/30" />
                <span className="h-2 w-3.5 rounded-sm border border-ink/30" />
              </span>
            </div>

            {/* Greeting */}
            <div className="mb-3 flex items-center justify-between px-1">
              <div>
                <p className="text-[8px] text-slate">Good morning</p>
                <p className="text-sm font-bold text-ink">Vikram</p>
              </div>
              <span className="rounded-full border border-mint-200 bg-mint-50 px-1.5 py-0.5 text-[7px] font-bold text-mint-800">
                VERIFIED
              </span>
            </div>

            {/* Balance panel */}
            <div className="rounded-2xl bg-ink p-3.5 text-white">
              <p className="text-[8px] text-white/50">Total outstanding</p>
              <p className="money mt-1 text-2xl font-bold leading-none tracking-tight">
                ₹1,42,850
              </p>

              <div className="mt-3 flex items-end justify-between">
                <div>
                  <p className="text-[7px] text-white/45">Available</p>
                  <p className="money mt-0.5 text-xs font-bold text-mint">₹5,07,150</p>
                </div>
                <span className="rounded-full bg-mint px-1.5 py-0.5 text-[7px] font-bold text-ink">
                  22% · Optimal
                </span>
              </div>

              <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/15">
                <div className="h-full w-[22%] rounded-full bg-mint" />
              </div>
            </div>

            {/* Due alert */}
            <div className="mt-2.5 rounded-xl border border-warn/30 bg-amber-50/60 p-2.5">
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <p className="text-[7px] font-bold uppercase tracking-wider text-warn">
                    Due soon
                  </p>
                  <p className="mt-0.5 truncate text-[10px] font-semibold text-ink">
                    HDFC Regalia
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="money text-xs font-bold text-ink">₹48,200</p>
                  <p className="text-[7px] text-slate">in 3 days</p>
                </div>
              </div>
            </div>

            {/* Card strip */}
            <p className="mb-1.5 mt-3 px-1 text-[7px] font-bold uppercase tracking-wider text-slate">
              Your cards
            </p>
            <div className="flex gap-2">
              {[
                { bg: 'linear-gradient(135deg,#004C8F,#00325E)', last4: '4821' },
                { bg: 'linear-gradient(135deg,#AE275F,#7A1A42)', last4: '9102' },
              ].map((card) => (
                <div
                  key={card.last4}
                  className="relative h-14 flex-1 overflow-hidden rounded-lg p-2"
                  style={{ backgroundImage: card.bg }}
                >
                  <span className="absolute -right-3 -top-4 h-12 w-12 rounded-full bg-white/10 blur-lg" />
                  <p className="money relative text-[7px] tracking-widest text-white/75">
                    •••• {card.last4}
                  </p>
                  <p className="money relative mt-2 text-[9px] font-bold text-white">
                    ₹3,00,000
                  </p>
                </div>
              ))}
            </div>

            {/* Activity */}
            <p className="mb-1.5 mt-3 px-1 text-[7px] font-bold uppercase tracking-wider text-slate">
              Recent
            </p>
            <div className="space-y-1.5">
              {[
                { label: 'Transfer to bank', amount: '−₹15,000' },
                { label: 'Bajaj EMI · Auto-pay', amount: '−₹4,250' },
              ].map((row) => (
                <div key={row.label} className="flex items-center gap-2 px-1">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-mint-50">
                    <span className="h-1.5 w-1.5 rounded-full bg-mint-600" />
                  </span>
                  <p className="min-w-0 flex-1 truncate text-[8px] font-medium text-ink">
                    {row.label}
                  </p>
                  <p className="money shrink-0 text-[9px] font-semibold text-ink">
                    {row.amount}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Side buttons */}
      <span className="absolute -left-[3px] top-24 h-10 w-[3px] rounded-l bg-ink/70" />
      <span className="absolute -left-[3px] top-40 h-16 w-[3px] rounded-l bg-ink/70" />
      <span className="absolute -right-[3px] top-32 h-20 w-[3px] rounded-r bg-ink/70" />
    </div>
  );
}

/* ── Showcase ───────────────────────────────────────────────────────────── */

export default function Showcase({ className }) {
  return (
    <div className={cx('relative select-none', className)} aria-hidden="true">
      {/* Ambient mint light. Kept low-opacity so the page still reads white. */}
      <span className="pointer-events-none absolute left-1/4 top-10 h-64 w-64 -translate-x-1/2 rounded-full bg-mint/25 blur-[90px]" />
      <span className="pointer-events-none absolute bottom-8 right-4 h-56 w-56 rounded-full bg-mint/20 blur-[80px]" />

      {/* Fine grid, for depth without clutter. */}
      <span
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #E6EAE8 1px, transparent 1px), linear-gradient(to bottom, #E6EAE8 1px, transparent 1px)',
          backgroundSize: '40px 40px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 72%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at center, black 30%, transparent 72%)',
        }}
      />

      <div className="relative mx-auto flex h-[560px] w-full max-w-[520px] items-center justify-center">
        {/* Back card — RuPay */}
        <CreditCard
          label="SBI SimplyCLICK"
          network="rupay"
          last4="1134"
          gradient="linear-gradient(135deg,#2C3E85 0%,#1B2A5E 55%,#141F46 100%)"
          className="absolute left-0 top-16 animate-float-slow"
          style={{ transform: 'rotate(-14deg)', animationDelay: '1.2s' }}
        />

        {/* Mid card — Mastercard */}
        <CreditCard
          label="ICICI Sapphiro"
          network="mastercard"
          last4="9102"
          gradient="linear-gradient(135deg,#B02C68 0%,#8A1F4C 55%,#5E1333 100%)"
          className="absolute left-6 top-44 animate-float"
          style={{ transform: 'rotate(-6deg)', animationDelay: '0.4s' }}
        />

        {/* Phone — the anchor */}
        <Phone
          className="relative z-20 animate-rise-in"
          style={{ animationDelay: '120ms' }}
        />

        {/* Front card — Visa, with the travelling sheen */}
        <CreditCard
          label="HDFC Regalia"
          network="visa"
          last4="4821"
          sheen
          gradient="linear-gradient(135deg,#0A0F0D 0%,#14211D 45%,#00614B 100%)"
          className="absolute -right-2 bottom-14 z-30 animate-float"
          style={{ transform: 'rotate(9deg)', animationDelay: '0.9s' }}
        />

        {/* Floating success chip — the product's payoff, stated once. */}
        <div
          className="absolute right-0 top-10 z-30 animate-float-slow rounded-2xl bg-canvas px-3.5 py-2.5 shadow-lift ring-1 ring-line"
          style={{ animationDelay: '0.2s' }}
        >
          <div className="flex items-center gap-2.5">
            <span className="relative grid h-8 w-8 shrink-0 place-items-center rounded-full bg-mint text-ink">
              <span className="absolute inset-0 animate-pulse-ring rounded-full bg-mint" />
              <svg viewBox="0 0 20 20" className="relative h-4 w-4" fill="none">
                <path
                  d="M5 10.5l3.5 3.5L15 7"
                  stroke="currentColor"
                  strokeWidth="2.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <div>
              <p className="text-[10px] font-bold text-ink">Transfer complete</p>
              <p className="money text-[9px] text-slate">₹10,000 · UTR 4471…</p>
            </div>
          </div>
        </div>

        {/* Floating auto-pay chip */}
        <div
          className="absolute bottom-4 left-2 z-30 animate-float rounded-2xl bg-ink px-3.5 py-2.5 shadow-lift"
          style={{ animationDelay: '1.6s' }}
        >
          <p className="text-[9px] font-bold text-mint">Auto-pay armed</p>
          <p className="money text-[9px] text-white/60">Bajaj · ₹4,250 · 5th</p>
        </div>
      </div>
    </div>
  );
}

/* Compact card, reused in the security section lower down the page. */
export { CreditCard };
