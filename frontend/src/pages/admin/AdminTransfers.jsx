import { useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Input, Row, Sheet, Skeleton, Tabs, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { dateTime, money, statusLabel, statusTone } from '../../utils/format';
import { AdminHeader, DataTable } from './AdminLayout';

/**
 * Transaction monitoring and the reversal queue (PRD 16.1).
 *
 * The "Stuck" tab is the one that matters: those are transfers where the card
 * is charged but the money has not reached the member. Every action here is
 * logged, and a reversal above the maker-checker threshold is held for a second
 * approver rather than executed.
 */
export default function AdminTransfers() {
  const toast = useToast();
  const { role } = useProfile();

  const [tab, setTab] = useState('stuck');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const canAct = ['L2_RISK_RECON', 'L3_SUPER_ADMIN'].includes(role);

  const { data: stuck, loading: stuckLoading, refetch: refetchStuck } = useFetch(
    () => endpoints.admin.stuckTransfers(),
    [],
  );
  const { data: all, loading: allLoading, refetch: refetchAll } = useFetch(
    () => endpoints.admin.transfers(search ? `?search=${encodeURIComponent(search)}` : ''),
    [search],
  );

  async function act(action, message) {
    if (!reason.trim()) {
      toast.error('A reason is required — it goes into the audit trail.');
      return;
    }

    setBusy(true);
    try {
      const response = await action();
      toast.success(response.message || message);
      setSelected(null);
      setReason('');
      refetchStuck();
      refetchAll();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  const stuckColumns = [
    {
      key: 'transfer_id',
      label: 'Transfer',
      render: (row) => (
        <span className="money text-2xs text-slate">{row.transfer_id.slice(0, 8)}…</span>
      ),
    },
    {
      key: 'principal_amount',
      label: 'Amount',
      render: (row) => (
        <span className="money font-semibold text-ink">{money(row.principal_amount)}</span>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>{statusLabel(row.status)}</Badge>
      ),
    },
    {
      key: 'stuck_for_hours',
      label: 'Stuck for',
      render: (row) => (
        <span
          className={cx(
            'money text-sm',
            row.stuck_for_hours > 2 ? 'font-semibold text-alert' : 'text-slate',
          )}
        >
          {row.stuck_for_hours != null ? `${row.stuck_for_hours}h` : '—'}
        </span>
      ),
    },
    {
      key: 'payout_retry_count',
      label: 'Retries',
      render: (row) => <span className="money text-slate">{row.payout_retry_count || 0}</span>,
    },
    {
      key: 'requires_maker_checker',
      label: 'Approval',
      render: (row) =>
        row.requires_maker_checker ? (
          <Badge tone="warn">Maker-checker</Badge>
        ) : (
          <span className="text-2xs text-slate">Single</span>
        ),
    },
  ];

  const allColumns = [
    {
      key: 'created_on',
      label: 'When',
      render: (row) => <span className="text-2xs text-slate">{dateTime(row.created_on)}</span>,
    },
    {
      key: 'principal_amount',
      label: 'Amount',
      render: (row) => (
        <span className="money font-semibold text-ink">{money(row.principal_amount)}</span>
      ),
    },
    {
      key: 'fee',
      label: 'Fee',
      render: (row) => <span className="money text-slate">{money(row.fee)}</span>,
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>{statusLabel(row.status)}</Badge>
      ),
    },
    {
      key: 'utr',
      label: 'UTR',
      render: (row) => <span className="money text-2xs text-slate">{row.utr || '—'}</span>,
    },
    {
      key: 'risk_score',
      label: 'Risk',
      render: (row) => (
        <span
          className={cx(
            'money text-sm',
            row.risk_score >= 60 ? 'text-warn' : 'text-slate',
          )}
        >
          {row.risk_score ?? '—'}
        </span>
      ),
    },
  ];

  const rows = tab === 'stuck' ? stuck : all;
  const loading = tab === 'stuck' ? stuckLoading : allLoading;

  return (
    <div>
      <AdminHeader
        title="Transfers"
        subtitle="Monitor volume and resolve transfers that did not complete."
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          tabs={[
            { value: 'stuck', label: 'Needs attention', count: stuck?.length },
            { value: 'all', label: 'All transfers' },
          ]}
          active={tab}
          onChange={setTab}
          className="w-full sm:w-auto"
        />

        {tab === 'all' && (
          <div className="w-full sm:w-72">
            <Input
              placeholder="Search by UTR or transfer id"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        )}
      </div>

      {loading ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          columns={tab === 'stuck' ? stuckColumns : allColumns}
          rows={(rows || []).map((row) => ({ ...row, id: row.transfer_id }))}
          empty={
            tab === 'stuck'
              ? 'No transfers need attention. Everything settled.'
              : 'No transfers found.'
          }
          onRowClick={canAct ? setSelected : undefined}
        />
      )}

      {!canAct && (
        <p className="mt-3 text-xs text-slate">
          Retrying a payout or reversing a transfer requires L2 Risk or L3 access.
        </p>
      )}

      <Sheet
        open={Boolean(selected)}
        onClose={() => {
          setSelected(null);
          setReason('');
        }}
        title="Resolve transfer"
        footer={
          selected && (
            <div className="space-y-2">
              {['PAYOUT_PROCESSING', 'PENDING_RECONCILIATION'].includes(selected.status) && (
                <Button
                  variant="mint"
                  size="lg"
                  full
                  loading={busy}
                  onClick={() =>
                    act(
                      () => endpoints.admin.retryPayout(selected.transfer_id, reason),
                      'Payout re-queued.',
                    )
                  }
                >
                  Retry payout
                </Button>
              )}

              <Button
                variant="danger"
                size="lg"
                full
                loading={busy}
                onClick={() =>
                  act(
                    () => endpoints.admin.reverse(selected.transfer_id, reason),
                    'Transfer reversed.',
                  )
                }
              >
                Reverse to card
              </Button>
            </div>
          )
        }
      >
        {selected && (
          <div className="space-y-4 pb-2">
            <Card className="divide-y divide-line py-1">
              <Row label="Transfer" value={selected.transfer_id} mono />
              <Row label="Status" value={statusLabel(selected.status)} />
              <Row label="Principal" value={money(selected.principal_amount)} mono />
              <Row
                label="Charged to card"
                value={money(selected.total_charged || selected.total_charged_to_card)}
                mono
              />
              {selected.utr && <Row label="UTR" value={selected.utr} mono />}
              <Row label="Payout retries" value={selected.payout_retry_count || 0} mono />
              {selected.failure_reason && (
                <Row label="Last failure" value={selected.failure_reason} tone="alert" />
              )}
            </Card>

            {selected.requires_maker_checker && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5">
                <p className="text-xs font-semibold text-amber-900">
                  Maker-checker required
                </p>
                <p className="mt-1 text-xs leading-relaxed text-amber-900/80">
                  This amount is above the approval threshold. If you are L2, your
                  reversal is queued for a senior administrator rather than
                  executed immediately.
                </p>
              </div>
            )}

            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink">
                Reason <span className="text-slate">(required)</span>
              </span>
              <textarea
                rows={3}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why are you taking this action?"
                className="w-full rounded-xl border border-line bg-canvas p-3 text-sm outline-none focus:border-ink/40"
              />
              <p className="mt-1.5 text-2xs text-slate">
                Recorded in the admin activity log against your user id.
              </p>
            </div>
          </div>
        )}
      </Sheet>
    </div>
  );
}
