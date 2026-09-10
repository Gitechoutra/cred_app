import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { Logo } from '../../components/layout/AppShell';
import { cx } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';

/**
 * Operations console shell (PRD section 16).
 *
 * Deliberately a different shape from the member app: this is a desk tool, so
 * it uses the full width and a persistent sidebar rather than the one-handed
 * phone column. Nav items are filtered by RBAC tier, so an L1 agent never sees
 * a door they cannot open.
 */

const NAV = [
  { to: '/admin', end: true, label: 'Overview', roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/users', label: 'Users', roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/kyc', label: 'KYC queue', roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/transfers', label: 'Transfers', roles: ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/reconciliation', label: 'Reconciliation', roles: ['L2_RISK_RECON', 'L3_SUPER_ADMIN'] },
  { to: '/admin/settings', label: 'Settings', roles: ['L3_SUPER_ADMIN'] },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { profile, role } = useProfile();

  const items = NAV.filter((item) => item.roles.includes(role));

  return (
    <div className="min-h-screen bg-mist">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl">
        {/* ── Sidebar ─────────────────────────────────────────────── */}
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-canvas p-4 lg:flex">
          <div className="flex items-center gap-2.5 px-1 pb-6">
            <Logo className="h-8 w-8" />
            <div>
              <p className="text-sm font-bold text-ink">CashU</p>
              <p className="text-2xs text-slate">Operations</p>
            </div>
          </div>

          <nav className="flex-1 space-y-1">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cx(
                    'block rounded-xl px-3 py-2.5 text-sm font-medium transition',
                    isActive ? 'bg-ink text-white' : 'text-slate hover:bg-mist hover:text-ink',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="space-y-2 border-t border-line pt-4">
            <div className="px-1">
              <p className="truncate text-xs font-medium text-ink">{profile?.full_name}</p>
              <p className="truncate text-2xs text-slate">{role?.replace(/_/g, ' ')}</p>
            </div>

            <button
              type="button"
              onClick={() => navigate('/home')}
              className="w-full rounded-xl px-3 py-2 text-left text-xs font-medium text-slate transition hover:bg-mist hover:text-ink"
            >
              Switch to member app
            </button>

            <button
              type="button"
              onClick={async () => {
                await signOut();
                navigate('/', { replace: true });
              }}
              className="w-full rounded-xl px-3 py-2 text-left text-xs font-medium text-slate transition hover:bg-mist hover:text-ink"
            >
              Sign out
            </button>
          </div>
        </aside>

        {/* ── Content ─────────────────────────────────────────────── */}
        <main className="min-w-0 flex-1">
          {/* Mobile nav - horizontal scroller, since a sidebar cannot fit. */}
          <div className="sticky top-0 z-30 border-b border-line bg-canvas lg:hidden">
            <div className="flex items-center gap-2 px-4 py-3">
              <Logo className="h-7 w-7" />
              <p className="flex-1 text-sm font-bold text-ink">CashU Operations</p>
              <button
                type="button"
                onClick={() => navigate('/home')}
                className="text-xs font-medium text-slate"
              >
                Exit
              </button>
            </div>

            <div className="sheet-scroll flex gap-1 overflow-x-auto px-4 pb-2">
              {items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cx(
                      'shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition',
                      isActive ? 'bg-ink text-white' : 'bg-mist text-slate',
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>

          <div className="p-4 lg:p-6">
            <Outlet />
          </div>
        </main>
      </div>
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
