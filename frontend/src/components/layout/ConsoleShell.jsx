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
 * told apart by its label and accent. Navigation is a tab strip under the
 * header rather than the member app's floating bar: a console has more
 * sections than fit in a phone-width pill, and the strip scrolls on a phone.
 *
 * `nav` items carry the roles that may see them. Hiding a tab is courtesy
 * only - every endpoint behind it checks the role on the server.
 */
export default function ConsoleShell({ nav, label, accentClass, badgeFor }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { signOut } = useAuth();
  const { profile, role } = useProfile();

  const items = nav.filter((item) => !item.roles || item.roles.includes(role));

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
      <header className="sticky top-0 z-40 border-b border-line bg-canvas/95 backdrop-blur">
        <div className="flex items-center gap-2.5 px-4 py-3 sm:px-6 lg:px-8">
          <Logo className="h-8 w-8 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-sm font-bold leading-none text-ink">CashU</p>
            <p className={cx('mt-1 text-2xs font-semibold', accentClass)}>{label}</p>
          </div>

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

        <nav aria-label={`${label} sections`} className="overflow-x-auto px-2 sm:px-4 lg:px-6">
          <div className="flex min-w-max gap-1 pb-2">
            {items.map((item) => {
              const Icon = item.icon;
              const badge = badgeFor?.(item);
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => cx(
                    'group flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium',
                    'transition-colors duration-base ease-glide',
                    isActive ? 'bg-ink text-white' : 'text-slate hover:bg-mist hover:text-ink',
                  )}
                >
                  {Icon && <Icon className="h-4 w-4" />}
                  {item.label}
                  {badge ? (
                    <span className="money ml-0.5 rounded-full bg-alert px-1.5 text-2xs font-bold text-white">
                      {badge}
                    </span>
                  ) : null}
                </NavLink>
              );
            })}
          </div>
        </nav>
      </header>

      <main className="min-w-0 p-4 sm:p-6 lg:px-8 lg:py-7">
        <div key={location.pathname} className="page-enter">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
