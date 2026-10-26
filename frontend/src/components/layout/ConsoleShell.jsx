import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { IconLock, IconLogout, IconUser, Logo } from './AppShell';
import { ProfileMenu } from './BottomNav';
import { cx } from '../ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import { initials } from '../../utils/format';

/**
 * The shell for the two staff consoles - admin and support desk.
 *
 * Same white canvas, type and components as the member app; the portal is
 * told apart by its label and accent. Sections live in a left sidebar:
 *
 *   lg and up   a fixed sidebar that collapses to an icon rail (remembered
 *               per browser) - more room for the wide tables when wanted
 *   below lg    a drawer from a menu button, closed on navigation, Escape or
 *               a tap outside, so a phone keeps the whole width for content
 *
 * `nav` items carry the roles that may see them. Hiding a link is courtesy
 * only - every endpoint behind it checks the role on the server.
 */

const COLLAPSE_KEY = 'cashu.console.sidebarCollapsed';

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

export default function ConsoleShell({ nav, label, accentClass, badgeFor }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { signOut } = useAuth();
  const { profile, role } = useProfile();

  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const items = nav.filter((item) => !item.roles || item.roles.includes(role));

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      /* private mode: the choice just is not remembered */
    }
  }, [collapsed]);

  // A link tapped in the drawer has done its job.
  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setDrawerOpen(false); };
    window.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);

  // Staff keep their own profile and security pages (MPIN, sessions); the
  // member features are not theirs to use.
  const menu = [
    { label: 'Profile', icon: IconUser, to: '/profile' },
    { label: 'Security', icon: IconLock, to: '/security' },
    { divider: true },
    {
      label: 'Logout',
      icon: IconLogout,
      tone: 'danger',
      onClick: async () => {
        await signOut();
        navigate('/', { replace: true });
      },
    },
  ];

  return (
    <div className="min-h-screen bg-canvas">
      {/* ── Sidebar, lg and up ─────────────────────────────────────── */}
      <aside
        className={cx(
          'fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-line bg-canvas lg:flex',
          'transition-[width] duration-base ease-glide',
          collapsed ? 'w-[76px]' : 'w-64',
        )}
        aria-label={`${label} navigation`}
      >
        <SidebarBrand label={label} accentClass={accentClass} collapsed={collapsed} />
        <SidebarLinks items={items} badgeFor={badgeFor} collapsed={collapsed} />
        <div className="border-t border-line p-3">
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cx(
              'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-slate',
              'transition-colors duration-base hover:bg-mist hover:text-ink',
              collapsed && 'justify-center px-0',
            )}
          >
            <CollapseIcon collapsed={collapsed} />
            {!collapsed && 'Collapse'}
          </button>
        </div>
      </aside>

      {/* ── Drawer, below lg ───────────────────────────────────────── */}
      <div
        className={cx('fixed inset-0 z-50 lg:hidden', drawerOpen ? 'pointer-events-auto' : 'pointer-events-none')}
        aria-hidden={!drawerOpen}
      >
        <button
          type="button"
          tabIndex={drawerOpen ? 0 : -1}
          aria-label="Close menu"
          onClick={() => setDrawerOpen(false)}
          className={cx(
            'absolute inset-0 bg-ink/30 backdrop-blur-sm transition-opacity duration-base',
            drawerOpen ? 'opacity-100' : 'opacity-0',
          )}
        />
        <aside
          id="console-drawer"
          className={cx(
            'absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-line bg-canvas shadow-lift',
            'transition-transform duration-base ease-glide',
            drawerOpen ? 'translate-x-0' : '-translate-x-full',
          )}
          aria-label={`${label} navigation`}
        >
          <div className="flex items-center justify-between pr-3">
            <SidebarBrand label={label} accentClass={accentClass} collapsed={false} />
            <button
              type="button"
              tabIndex={drawerOpen ? 0 : -1}
              onClick={() => setDrawerOpen(false)}
              aria-label="Close menu"
              className="grid h-9 w-9 place-items-center rounded-xl text-slate hover:bg-mist hover:text-ink"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <SidebarLinks items={items} badgeFor={badgeFor} collapsed={false} tabbable={drawerOpen} />
        </aside>
      </div>

      {/* ── Top bar + content ──────────────────────────────────────── */}
      <div className={cx('transition-[padding] duration-base ease-glide', collapsed ? 'lg:pl-[76px]' : 'lg:pl-64')}>
        <header className="sticky top-0 z-30 border-b border-line bg-canvas/95 backdrop-blur">
          <div className="flex items-center gap-2.5 px-4 py-3 sm:px-6 lg:px-8">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open menu"
              aria-controls="console-drawer"
              aria-expanded={drawerOpen}
              className="grid h-10 w-10 place-items-center rounded-xl border border-line text-ink transition-colors hover:bg-mist lg:hidden"
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" aria-hidden="true">
                <path d="M3.5 5.5h13M3.5 10h13M3.5 14.5h13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>

            {/* On small screens the brand sits in the bar, as the sidebar is hidden. */}
            <div className="flex min-w-0 items-center gap-2.5 lg:hidden">
              <Logo className="h-8 w-8 shrink-0" />
              <div className="min-w-0">
                <p className="truncate text-sm font-bold leading-none text-ink">CashU</p>
                <p className={cx('mt-1 text-2xs font-semibold', accentClass)}>{label}</p>
              </div>
            </div>

            <p className="hidden truncate text-sm font-semibold text-ink lg:block">
              {currentTitle(items, location.pathname) || label}
            </p>

            <span className="ml-auto hidden truncate rounded-full border border-line bg-canvas px-2.5 py-1 text-2xs font-semibold text-slate sm:inline-block">
              {role?.replace(/_/g, ' ')}
            </span>

            <div className="ml-auto flex items-center gap-2 sm:ml-3">
              <ProfileMenu
                name={profile?.full_name}
                detail={role?.replace(/_/g, ' ')}
                avatar={initials(profile?.full_name)}
                items={menu}
                placement="bottom"
              />
            </div>
          </div>
        </header>

        <main className="min-w-0 p-4 sm:p-6 lg:px-8 lg:py-7">
          <div key={location.pathname} className="page-enter">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** The section the current path belongs to, for the top bar's title. */
function currentTitle(items, pathname) {
  const match = items
    .filter((item) => (item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return match?.label;
}

function SidebarBrand({ label, accentClass, collapsed }) {
  return (
    <div className={cx('flex h-[65px] shrink-0 items-center gap-2.5 px-5', collapsed && 'justify-center px-0')}>
      <Logo className="h-8 w-8 shrink-0" />
      {!collapsed && (
        <div className="min-w-0">
          <p className="truncate text-sm font-bold leading-none text-ink">CashU</p>
          <p className={cx('mt-1 text-2xs font-semibold', accentClass)}>{label}</p>
        </div>
      )}
    </div>
  );
}

function SidebarLinks({ items, badgeFor, collapsed, tabbable = true }) {
  return (
    <nav className="flex-1 overflow-y-auto px-3 py-2">
      <ul className="space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const badge = badgeFor?.(item);
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                tabIndex={tabbable ? 0 : -1}
                title={collapsed ? item.label : undefined}
                aria-label={collapsed ? item.label : undefined}
                className={({ isActive }) => cx(
                  'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium',
                  'transition-colors duration-base ease-glide',
                  collapsed && 'justify-center px-0',
                  isActive ? 'bg-ink text-white' : 'text-slate hover:bg-mist hover:text-ink',
                )}
              >
                {Icon && <Icon className="h-[18px] w-[18px] shrink-0" />}
                {!collapsed && <span className="min-w-0 flex-1 truncate">{item.label}</span>}
                {badge ? (
                  collapsed ? (
                    <span className="absolute right-3 top-2 h-2 w-2 rounded-full bg-alert" aria-label={`${badge} open`} />
                  ) : (
                    <span className="money rounded-full bg-alert px-1.5 text-2xs font-bold text-white">{badge}</span>
                  )
                ) : null}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function CollapseIcon({ collapsed }) {
  return (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px] shrink-0" fill="none" aria-hidden="true">
      <rect x="3" y="3.5" width="14" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 3.5v13" stroke="currentColor" strokeWidth="1.6" />
      <path
        d={collapsed ? 'M11.5 8l2 2-2 2' : 'M13.5 8l-2 2 2 2'}
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
