import { useEffect, useState } from 'react';

import { endpoints } from '../../api/client';
import ConsoleShell from '../../components/layout/ConsoleShell';
import {
  IconAlert,
  IconCard,
  IconHelp,
  IconHome,
  IconLock,
  IconPay,
  IconReceipt,
  IconShield,
  IconUser,
} from '../../components/layout/AppShell';
import { cx } from '../../components/ui';

/**
 * Admin console shell (PRD section 16): L2 risk & reconciliation and L3 super
 * admins. Support agents have their own portal, the support desk.
 *
 * Sidebar links are filtered by role so nobody sees a door they cannot open; the
 * server checks the role on every endpoint regardless.
 */

const L2 = 'L2_RISK_RECON';
const L3 = 'L3_SUPER_ADMIN';

const NAV = [
  { to: '/admin', end: true, label: 'Overview', icon: IconHome, roles: [L2, L3] },
  { to: '/admin/users', label: 'Users', icon: IconUser, roles: [L2, L3] },
  { to: '/admin/kyc', label: 'KYC', icon: IconShield, roles: [L2, L3] },
  { to: '/admin/credit', label: 'Credit', icon: IconCard, roles: [L2, L3] },
  { to: '/admin/payments', label: 'Payments', icon: IconPay, roles: [L2, L3] },
  { to: '/admin/errors', label: 'Error log', icon: IconAlert, roles: [L2, L3] },
  { to: '/admin/cards', label: 'Card records', icon: IconCard, roles: [L2, L3] },
  { id: 'escalations', to: '/admin/escalations', label: 'Escalations', icon: IconHelp, roles: [L2, L3] },
  { to: '/admin/staff', label: 'Staff', icon: IconUser, roles: [L3] },
  { to: '/admin/reconciliation', label: 'Recon', icon: IconReceipt, roles: [L2, L3] },
  { to: '/admin/settings', label: 'Settings', icon: IconLock, roles: [L3] },
];

export default function AdminLayout() {
  const [openEscalations, setOpenEscalations] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = () => endpoints.admin.escalationCount()
      .then((r) => alive && setOpenEscalations(r.data?.open_escalations || 0))
      .catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  return (
    <ConsoleShell
      nav={NAV}
      label="Operations"
      accentClass="text-ink"
      badgeFor={(item) => (item.id === 'escalations' ? openEscalations : 0)}
    />
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
