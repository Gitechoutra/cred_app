import { Outlet, useNavigate } from 'react-router-dom';

import {
  IconHome,
  IconLock,
  IconHelp,
  IconLogout,
  IconReceipt,
  IconShield,
  IconUser,
  Logo,
} from '../../components/layout/AppShell';
import { BottomNav, ProfileMenu } from '../../components/layout/BottomNav';
import { cx } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import { initials } from '../../utils/format';

/**
 * Operations console shell (PRD section 16).
 *
 * Shares the member app's bottom navigation so the product reads as one thing,
 * but keeps its own full-bleed content area: this is a desk tool, and the
 * transaction and audit tables want every pixel of width they can get.
 *
 * Nav items are filtered by RBAC tier, so an L1 agent never sees a door they
 * cannot open - which also keeps the bar short for the lower tiers.
 */

const NAV = [
  { to: '/admin', end: true, label: 'Overview', icon: IconHome, roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/users', label: 'Users', icon: IconUser, roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/kyc', label: 'KYC', icon: IconShield, roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/reconciliation', label: 'Recon', icon: IconReceipt, roles: ['L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/settings', label: 'Settings', icon: IconLock, roles: ['L3_SUPER_ADMIN'] },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { profile, role } = useProfile();

  const items = NAV.filter((item) => item.roles.includes(role));

  // The same menu a member gets, in the same place. An operator is also a user
  // of this product - they have a profile, an MPIN and devices - and the
  // console offering a different shape was just an inconsistency.
  const profileMenuItems = [
    { label: 'Profile', icon: IconUser, to: '/profile' },
    { label: 'Security', icon: IconLock, to: '/security' },
    { label: 'Help & support', icon: IconHelp, to: '/support' },
    { divider: true },
    { label: 'Switch to member app', icon: IconHome, to: '/home' },
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
    <div className="min-h-screen bg-canvas pb-24 sm:pb-28">
      <header className="sticky top-0 z-40 border-b border-line bg-canvas/95 backdrop-blur">
        <div className="flex items-center gap-2.5 px-4 py-3 sm:px-6 lg:px-8">
          <Logo className="h-8 w-8 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-sm font-bold leading-none text-ink">CashU</p>
            <p className="mt-1 text-2xs text-slate">Operations</p>
          </div>

          <span className="ml-auto hidden truncate rounded-full border border-line bg-canvas px-2.5 py-1 text-2xs font-semibold text-slate sm:inline-block">
            {role?.replace(/_/g, ' ')}
          </span>

          {/* Top right, as on the member side. `placement="bottom"` because
              this one hangs off a bar at the top of the page, not the bottom. */}
          <div className="ml-auto flex items-center gap-2 sm:ml-3">
            <ProfileMenu
              name={profile?.full_name}
              detail={role?.replace(/_/g, ' ')}
              avatar={initials(profile?.full_name)}
              items={profileMenuItems}
              placement="bottom"
            />
          </div>
        </div>
      </header>

      {/* Full bleed, deliberately. A capped, centred container leaves dead space
          down both sides of a wide monitor. */}
      <main className="min-w-0 p-4 sm:p-6 lg:px-8 lg:py-7">
        <Outlet />
      </main>

      <BottomNav items={items} />
    </div>
  );
}
/* ── Shared admin pieces ────────────────────────────────────────────────── */

export function AdminHeader({ title, subtitle, action }) {
  return (
    <header className="mb-5 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-bold text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

export function StatCard({ label, value, hint, tone = 'neutral' }) {
  return (
    <div className="rounded-2xl border border-line bg-canvas p-4">
      <p className="text-2xs font-semibold uppercase tracking-wider text-slate">{label}</p>
      <p
        className={cx(
          'money mt-1.5 text-2xl font-bold',
          tone === 'good' && 'text-mint-700',
          tone === 'alert' && 'text-alert',
          tone === 'neutral' && 'text-ink',
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-2xs text-slate">{hint}</p>}
    </div>
  );
}

export function DataTable({ columns, rows, empty, onRowClick }) {
  if (!rows?.length) {
    return (
      <div className="rounded-2xl border border-line bg-canvas py-16 text-center">
        <p className="text-sm text-slate">{empty || 'Nothing to show.'}</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-canvas">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-line bg-mist/60">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className="whitespace-nowrap px-4 py-3 text-2xs font-semibold uppercase tracking-wider text-slate"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-line">
            {rows.map((row, index) => (
              <tr
                key={row.id || index}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cx(
                  'transition',
                  onRowClick && 'cursor-pointer hover:bg-mist/50',
                )}
              >
                {columns.map((column) => (
                  <td key={column.key} className="whitespace-nowrap px-4 py-3 text-ink">
                    {column.render ? column.render(row) : row[column.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
