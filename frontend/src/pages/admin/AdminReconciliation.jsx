import { useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime, money, titleCase } from '../../utils/format';
import { AdminHeader, DataTable, StatCard } from './AdminLayout';

/**
 * Reconciliation console (PRD 16.1, 9.4).
 *
 * The self-audit button is the important one. On MySQL the ledger's balancing
 * guarantee rests on application discipline rather than the database's
 * strictest isolation, so it is verified rather than assumed. An
 * UNBALANCED_LEDGER finding means ledger_engine.post was bypassed somewhere -
 * the most severe class of bug this platform can have.
 */
export default function AdminReconciliation() {
  const toast = useToast();

  const { data, loading, refetch } = useFetch(() => endpoints.admin.reconciliation(), []);

  const [audit, setAudit] = useState(null);
  const [auditing, setAuditing] = useState(false);

  async function runAudit() {
    setAuditing(true);
    try {
      const response = await endpoints.admin.selfAudit();
      setAudit(response.data);

      if (response.data.healthy) toast.success('Ledger integrity verified.');
      else toast.error('Ledger integrity check found discrepancies.');

      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setAuditing(false);
    }
  }

  const columns = [
    {
      key: 'discrepancy_type',
      label: 'Type',
      render: (row) => (
        <Badge tone={row.discrepancy_type === 'UNBALANCED_LEDGER' ? 'alert' : 'warn'}>
          {titleCase(row.discrepancy_type)}
        </Badge>
      ),
    },
    {
      key: 'transaction_id',
      label: 'Transaction',
      render: (row) => (
        <span className="money text-2xs text-slate">
          {row.transaction_id ? `${row.transaction_id.slice(0, 8)}…` : '—'}
        </span>
      ),
    },
    {
      key: 'expected_amount',
      label: 'Expected',
      render: (row) => (
        <span className="money text-slate">
          {row.expected_amount != null ? money(row.expected_amount) : '—'}
        </span>
      ),
    },
    {
      key: 'actual_amount',
      label: 'Actual',
      render: (row) => (
        <span className="money text-slate">
          {row.actual_amount != null ? money(row.actual_amount) : '—'}
        </span>
      ),
    },
    {
      key: 'details',
      label: 'Details',
      render: (row) => (
        <span className="text-2xs text-slate">{row.details || '—'}</span>
      ),
    },
    {
      key: 'created_on',
      label: 'Raised',
      render: (row) => (
        <span className="text-2xs text-slate">{dateTime(row.created_on)}</span>
      ),
    },
  ];

  return (
    <div>
      <AdminHeader
        title="Reconciliation"
        subtitle="Three-way settlement matching and ledger integrity."
        action={
          <Button variant="mint" size="md" loading={auditing} onClick={runAudit}>
            Run integrity check
          </Button>
        }
      />

      {/* ── Audit result ────────────────────────────────────────────── */}
      {audit && (
        <div
          className={cx(
            'mb-5 rounded-2xl border p-4',
            audit.healthy ? 'border-mint-200 bg-mint-50' : 'border-alert/30 bg-red-50',
          )}
        >
          <div className="flex items-center gap-2">
            <span
              className={cx(
                'h-2 w-2 rounded-full',
                audit.healthy ? 'bg-mint-600' : 'bg-alert',
              )}
            />
            <p className="text-sm font-semibold text-ink">
              {audit.healthy
                ? 'Ledger balances. Every transaction has matching debits and credits.'
                : 'Ledger drift detected — investigate immediately.'}
            </p>
          </div>

          <div className="mt-3 flex gap-6">
            <div>
              <p className="text-2xs uppercase tracking-wider text-slate">Unbalanced</p>
              <p className="money mt-0.5 text-lg font-bold text-ink">
                {audit.unbalanced_count}
              </p>
            </div>
            <div>
              <p className="text-2xs uppercase tracking-wider text-slate">Orphaned</p>
              <p className="money mt-0.5 text-lg font-bold text-ink">
                {audit.orphan_count}
              </p>
            </div>
          </div>

          {!audit.healthy && (
            <p className="mt-3 text-xs leading-relaxed text-alert/85">
              A transaction whose entries do not balance means a money path wrote
              outside the ledger engine. Treat this as a production incident.
            </p>
          )}
        </div>
      )}

      {/* ── Open discrepancies ──────────────────────────────────────── */}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <StatCard
          label="Open discrepancies"
          value={data?.length ?? 0}
          tone={data?.length ? 'alert' : 'good'}
        />
        <StatCard
          label="Unreconciled"
          value={data?.unreconciled_transactions ?? 0}
          hint="Settled but not yet matched"
        />
        <StatCard
          label="Audit cadence"
          value="Nightly"
          hint="Plus every 6 hours for settlement"
        />
      </div>

      {loading ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          columns={columns}
          rows={(data || []).map((row) => ({ ...row, id: row.discrepancy_id }))}
          empty="No open discrepancies. Every transaction reconciles."
        />
      )}
    </div>
  );
}
