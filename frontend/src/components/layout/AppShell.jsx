import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { cx } from '../ui';
import { BottomNav, ProfileMenu } from './BottomNav';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import { initials } from '../../utils/format';

/**
 * CashU application shell.
 *
 * Navigation lives at the bottom of the screen, PhonePe-style: five primary
 * destinations plus an account slot on the right. A bottom bar beats a sidebar
 * here because the destinations are few, flat and equally weighted, and because
 * it gives the content the full width of the window on every breakpoint.
 *
 * The top bar keeps only what is contextual - who you are, your KYC state,
 * notifications - rather than duplicating the navigation underneath it.
 */

/* Five slots is the ceiling before labels start truncating at 320px. Bank
   accounts sits in the account menu instead, where Profile already links to
   it, rather than squeezing a sixth slot into the bar. */
const NAV = [
  { to: '/home', label: 'Home', icon: IconHome, end: true },
  { to: '/cards', label: 'Cards', icon: IconCard },
  { to: '/transfer', label: 'Transfer', icon: IconTransfer },
  { to: '/emi', label: 'EMIs', icon: IconEmi },
  { to: '/transactions', label: 'History', icon: IconReceipt },
];

export default function AppShell({ children }) {
  return (
    /* The bottom padding reserves room for the fixed bar; without it the last
       card on every page sits underneath the navigation. */
    <div className="min-h-screen bg-canvas pb-24 sm:pb-28">
      <TopBar />

      <main className="px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <div className="mx-auto w-full max-w-6xl">{children}</div>
      </main>

      <footer className="border-t border-line bg-canvas px-4 py-4 sm:px-6 lg:px-8">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2">
          <p className="text-2xs text-slate">
            CashU v1.0 — your cards and EMIs, under one glass pane.
          </p>
          <p className="text-2xs text-slate-light">
            Cards are tokenised under RBI Card-on-File rules. We never store
            your card number, CVV or PIN.
          </p>
        </div>
      </footer>

      <MemberNav />
    </div>
  );
}

/* ── Bottom navigation ──────────────────────────────────────────────────── */

function MemberNav() {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { profile, isAdmin } = useProfile();

  const items = [
    { label: 'Profile', icon: IconUser, to: '/profile' },
    { label: 'Security', icon: IconLock, to: '/security' },
    { label: 'Bank accounts', icon: IconBank, to: '/banks' },
    { label: 'Help & support', icon: IconHelp, to: '/support' },
  ];

  /* Carried over from the old sidebar: an operator working in the member app
     needs a way back to the console. */
  if (isAdmin) {
    items.push({ divider: true });
    items.push({ label: 'Operations console', icon: IconShield, to: '/admin' });
  }

  items.push({ divider: true });
  items.push({
    label: 'Logout',
    icon: IconLogout,
    tone: 'danger',
    onClick: async () => {
      await signOut();
      navigate('/', { replace: true });
    },
  });

  return (
    <BottomNav items={NAV}>
      <ProfileMenu
        name={profile?.full_name}
        detail={profile?.phone ? `+91 ${profile.phone}` : null}
        avatar={initials(profile?.full_name)}
        items={items}
      />
    </BottomNav>
  );
}

/* ── Top bar ────────────────────────────────────────────────────────────── */

function TopBar() {
  const navigate = useNavigate();
  const { profile, kycStatus } = useProfile();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
        {/* The sidebar used to carry the brand; with it gone, the mark lives
            here so the app is still identifiable on every page. */}
        <button
          type="button"
          onClick={() => navigate('/home')}
          aria-label="CashU home"
          className="flex shrink-0 items-center gap-2.5 rounded-xl text-left"
        >
          <Logo className="h-9 w-9" />
          <span className="hidden sm:block">
            <span className="block text-sm font-bold leading-none text-ink">CashU</span>
            <span className="mt-1 block text-2xs text-slate">Credit &amp; EMI hub</span>
          </span>
        </button>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink sm:text-right lg:text-left">
            {greeting()}, {(profile?.full_name || '').split(' ')[0] || 'there'}
          </p>
        </div>

        {kycStatus === 'APPROVED' ? (
          <span className="hidden items-center gap-1.5 rounded-full border border-mint-200 bg-mint-50 px-2.5 py-1 text-2xs font-semibold text-mint-800 sm:inline-flex">
            <IconShield className="h-3 w-3" />
            KYC verified
          </span>
        ) : (
          <button
            type="button"
            onClick={() => navigate('/kyc')}
            className="rounded-full border border-line bg-canvas px-2.5 py-1 text-2xs font-semibold text-slate transition hover:bg-mist hover:text-ink"
          >
            Verify KYC
          </button>
        )}

        <NotificationBell />
      </div>
    </header>
  );
}

function NotificationBell() {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const response = await endpoints.notifications.list();
        if (!cancelled) setUnread(response.unread_count || 0);
      } catch {
        /* A failed badge count must not disturb the page. */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <button
      type="button"
      onClick={() => navigate('/notifications')}
      aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}
      className="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink transition hover:bg-mist"
    >
      <IconBell className="h-5 w-5" />
      {unread > 0 && (
        <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-alert px-1 text-[9px] font-bold text-white">
          {unread > 9 ? '9+' : unread}
        </span>
      )}
    </button>
  );
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

/* ── Page primitives ────────────────────────────────────────────────────── */

/**
 * Standard page header for a web view.
 *
 * `back` is optional here in a way it was not on mobile - a web app has
 * persistent navigation, so a back affordance is only offered on the drill-down
 * pages where it genuinely helps.
 */
export function PageHeader({ title, subtitle, back, action }) {
  const navigate = useNavigate();

  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3">
        {back && (
          <button
            type="button"
            onClick={() => (typeof back === 'string' ? navigate(back) : back === true ? navigate(-1) : back())}
            aria-label="Go back"
            className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-canvas text-ink transition hover:bg-mist"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
              <path
                d="M12 4l-6 6 6 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}

        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-slate">{subtitle}</p>}
        </div>
      </div>

      {action}
    </header>
  );
}

/**
 * Centred column for focused flows.
 *
 * Forms and single-purpose flows read badly at full width - a 1400px-wide OTP
 * field is absurd - so these stay in a measured column while dashboards and
 * tables use the whole content area.
 */
export function NarrowPage({ children, className }) {
  return <div className={cx('mx-auto w-full max-w-2xl', className)}>{children}</div>;
}

/** Full-bleed page card used to frame standalone flows on the mist background. */
export function Panel({ children, className }) {
  return (
    <div className={cx('rounded-2xl border border-line bg-canvas p-5 sm:p-6', className)}>
      {children}
    </div>
  );
}

/* ── Logo ───────────────────────────────────────────────────────────────── */

export function Logo({ className = 'h-9 w-9' }) {
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

/* ── Icons ──────────────────────────────────────────────────────────────── */

function base(props) {
  return {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    ...props,
  };
}

export function IconHome(props) {
  return (
    <svg {...base(props)}>
      <path d="M3 10.5L12 3l9 7.5" />
      <path d="M5 9.5V20h14V9.5" />
    </svg>
  );
}

export function IconCard(props) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="5" width="19" height="14" rx="3" />
      <path d="M2.5 9.5h19" />
    </svg>
  );
}

export function IconTransfer(props) {
  return (
    <svg {...base(props)}>
      <path d="M4 8h13M13 4l4 4-4 4" />
      <path d="M20 16H7M11 20l-4-4 4-4" />
    </svg>
  );
}

export function IconEmi(props) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="18" height="17" rx="3" />
      <path d="M3 9h18M8 2.5v3M16 2.5v3M8 14h8" />
    </svg>
  );
}

export function IconUser(props) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M4.5 20c1-3.6 4-5.5 7.5-5.5s6.5 1.9 7.5 5.5" />
    </svg>
  );
}

export function IconBell(props) {
  return (
    <svg {...base(props)}>
      <path d="M6 9a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 13 6 9z" />
      <path d="M10 18.5a2 2 0 0 0 4 0" />
    </svg>
  );
}

export function IconShield(props) {
  return (
    <svg {...base(props)}>
      <path d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export function IconBank(props) {
  return (
    <svg {...base(props)}>
      <path d="M3 9.5L12 4l9 5.5" />
      <path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18" />
    </svg>
  );
}

export function IconPlus(props) {
  return (
    <svg {...base(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconChevron(props) {
  return (
    <svg {...base(props)}>
      <path d="M9 5l7 7-7 7" />
    </svg>
  );
}

export function IconCheck(props) {
  return (
    <svg {...base(props)}>
      <path d="M4 12.5l5 5 11-11" />
    </svg>
  );
}

export function IconClock(props) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.5l3.5 2" />
    </svg>
  );
}

export function IconAlert(props) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5M12 16h.01" />
    </svg>
  );
}

export function IconReceipt(props) {
  return (
    <svg {...base(props)}>
      <path d="M5 3h14v18l-2.5-1.5L14 21l-2-1.5L10 21l-2.5-1.5L5 21z" />
      <path d="M9 8h6M9 12h6" />
    </svg>
  );
}

export function IconLock(props) {
  return (
    <svg {...base(props)}>
      <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

export function IconHelp(props) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.2 2.4c-.6.2-.7.6-.7 1.1v.5M12 16.5h.01" />
    </svg>
  );
}

export function IconLogout(props) {
  return (
    <svg {...base(props)}>
      <path d="M15 17l5-5-5-5" />
      <path d="M20 12H9" />
      <path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6" />
    </svg>
  );
}
