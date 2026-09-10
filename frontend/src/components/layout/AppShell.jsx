import { NavLink, useLocation, useNavigate } from 'react-router-dom';

import { cx } from '../ui';
import { useProfile } from '../../hooks/useProfile';

/**
 * The member app shell.
 *
 * Mobile-first with a fixed bottom bar, widening to a centred column on
 * desktop. The layout never exceeds a phone-width column, because CashU is a
 * one-handed app and stretching a payment flow across 1400px would break that.
 */

const NAV = [
  { to: '/home', label: 'Home', icon: IconHome },
  { to: '/cards', label: 'Cards', icon: IconCard },
  { to: '/transfer', label: 'Transfer', icon: IconTransfer, accent: true },
  { to: '/emi', label: 'EMIs', icon: IconEmi },
  { to: '/profile', label: 'Profile', icon: IconUser },
];

export default function AppShell({ children }) {
  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto min-h-screen w-full max-w-md pb-24">{children}</div>
      <BottomNav />
    </div>
  );
}

function BottomNav() {
  const { pathname } = useLocation();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-canvas/95 backdrop-blur"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="mx-auto flex w-full max-w-md items-stretch">
        {NAV.map(({ to, label, icon: Icon, accent }) => {
          const active = pathname === to || pathname.startsWith(`${to}/`);

          return (
            <NavLink
              key={to}
              to={to}
              className="relative flex flex-1 flex-col items-center gap-1 py-2.5"
              aria-current={active ? 'page' : undefined}
            >
              {accent ? (
                <span
                  className={cx(
                    'grid h-11 w-11 -mt-5 place-items-center rounded-2xl transition-all',
                    'bg-mint text-ink shadow-mint',
                    active && 'scale-105',
                  )}
                >
                  <Icon className="h-5 w-5" />
                </span>
              ) : (
                <Icon
                  className={cx('h-5 w-5 transition-colors', active ? 'text-ink' : 'text-slate-light')}
                />
              )}

              <span
                className={cx(
                  'text-2xs font-medium transition-colors',
                  active ? 'text-ink' : 'text-slate-light',
                )}
              >
                {label}
              </span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

/* ── Page header ────────────────────────────────────────────────────────── */

export function PageHeader({ title, subtitle, back, action, sticky = true }) {
  const navigate = useNavigate();

  return (
    <header
      className={cx(
        'flex items-center gap-3 bg-canvas px-4 py-3',
        sticky && 'sticky top-0 z-30 border-b border-line',
      )}
    >
      {back && (
        <button
          type="button"
          onClick={() => (typeof back === 'string' ? navigate(back) : navigate(-1))}
          aria-label="Go back"
          className="-ml-1 grid h-9 w-9 shrink-0 place-items-center rounded-full text-ink transition hover:bg-mist"
        >
          <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none">
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

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-lg font-semibold text-ink">{title}</h1>
        {subtitle && <p className="truncate text-xs text-slate">{subtitle}</p>}
      </div>

      {action}
    </header>
  );
}

/* ── Home header ────────────────────────────────────────────────────────── */

export function HomeHeader({ unreadCount = 0, kycStatus }) {
  const navigate = useNavigate();
  const { firstName } = useProfile();

  return (
    <header className="flex items-center gap-3 px-4 pt-5 pb-3">
      <div className="min-w-0 flex-1">
        <p className="text-xs text-slate">Hello,</p>
        <h1 className="truncate text-xl font-bold text-ink">{firstName}</h1>
      </div>

      {kycStatus === 'APPROVED' ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-mint-200 bg-mint-50 px-2.5 py-1 text-2xs font-semibold text-mint-800">
          <IconShield className="h-3 w-3" />
          Verified
        </span>
      ) : (
        <button
          type="button"
          onClick={() => navigate('/kyc')}
          className="rounded-full border border-line bg-mist px-2.5 py-1 text-2xs font-semibold text-slate"
        >
          Verify KYC
        </button>
      )}

      <button
        type="button"
        onClick={() => navigate('/notifications')}
        aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ''}`}
        className="relative grid h-9 w-9 place-items-center rounded-full text-ink transition hover:bg-mist"
      >
        <IconBell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute right-1.5 top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-alert px-1 text-[9px] font-bold text-white">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>
    </header>
  );
}

/* ── Icons ──────────────────────────────────────────────────────────────── */
/* Inline so the bundle carries no icon-font or library dependency. */

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
