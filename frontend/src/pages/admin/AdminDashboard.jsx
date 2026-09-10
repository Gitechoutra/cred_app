import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Skeleton, cx } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { money, moneyCompact } from '../../utils/format';
import { AdminHeader, StatCard } from './AdminLayout';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { data, loading } = useFetch(() => endpoints.admin.dashboard(), []);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <AdminHeader
        title="Operations overview"
        subtitle="Platform health, volume and anything that needs attention."
      />

      {/* ── Alerts first ────────────────────────────────────────────── */}
      {data.alerts?.length > 0 && (
        <div className="mb-5 space-y-2">
          {data.alerts.map((alert) => (
            <button
              key={alert.message}
              type="button"
              onClick={() => navigate(`/admin/${alert.action}`)}
              className={cx(
                'flex w-full items-center gap-3 rounded-xl border p-3.5 text-left transition hover:shadow-card',
                alert.severity === 'critical' && 'border-alert/30 bg-red-50',
                alert.severity === 'warning' && 'border-warn/30 bg-amber-50',
                alert.severity === 'info' && 'border-line bg-canvas',
              )}
            >
              <span
                className={cx(
                  'h-2 w-2 shrink-0 rounded-full',
                  alert.severity === 'critical' && 'bg-alert',
                  alert.severity === 'warning' && 'bg-warn',
                  alert.severity === 'info' && 'bg-slate-light',
                )}
              />
              <p className="flex-1 text-sm font-medium text-ink">{alert.message}</p>
              <span className="text-xs font-semibold text-slate">Review →</span>
            </button>
          ))}
        </div>
      )}

      {/* ── Volume ──────────────────────────────────────────────────── */}
      <section className="mb-5">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate">
          This month
        </h2>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Transfer volume"
            value={moneyCompact(data.transfers.month_volume)}
            hint={`${data.transfers.today} transfers today`}
          />
          <StatCard
            label="Fee revenue"
            value={moneyCompact(data.transfers.month_fee_revenue)}
            tone="good"
          />
          <StatCard
            label="Success rate"
            value={
              data.transfers.success_rate !== null
                ? `${data.transfers.success_rate}%`
                : '—'
            }
            hint="Target > 97.5%"
            tone={
              data.transfers.success_rate === null
                ? 'neutral'
                : data.transfers.success_rate >= 97.5
                  ? 'good'
                  : 'alert'
            }
          />
          <StatCard
            label="Stuck transfers"
            value={data.transfers.stuck_count}
            hint="Charged but not settled"
            tone={data.transfers.stuck_count > 0 ? 'alert' : 'good'}
          />
        </div>
      </section>

      {/* ── Users ───────────────────────────────────────────────────── */}
      <section className="mb-5">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate">
          Members
        </h2>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total users" value={data.users.total} />
          <StatCard label="Active" value={data.users.active} tone="good" />
          <StatCard label="KYC verified" value={data.users.kyc_verified} />
          <StatCard
            label="KYC pending"
            value={data.users.pending_kyc_reviews}
            hint="Awaiting review"
            tone={data.users.pending_kyc_reviews > 0 ? 'alert' : 'neutral'}
          />
        </div>
      </section>

      {/* ── EMI & operations ────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate">
          EMI and operations
        </h2>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Active loans" value={data.emi.active_obligations} />
          <StatCard label="Active mandates" value={data.emi.active_mandates} />
          <StatCard label="Cards linked" value={data.operations.cards_linked} />
          <StatCard
            label="Open discrepancies"
            value={data.operations.open_discrepancies}
            tone={data.operations.open_discrepancies > 0 ? 'alert' : 'good'}
          />
        </div>
      </section>
    </div>
  );
}
