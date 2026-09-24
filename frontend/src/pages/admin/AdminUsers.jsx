import { useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Input, Row, Sheet, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { date, money, statusLabel, statusTone } from '../../utils/format';
import { AdminHeader, DataTable } from './AdminLayout';

/**
 * User 360 viewer (PRD 16.1).
 *
 * Search accepts a phone number, a name, or a transaction UTR - the last is how
 * a support agent actually arrives, holding a customer's receipt.
 *
 * PII stays masked for L1. L2 and L3 see raw values, and opening this view
 * writes an audit row naming the viewer (PRD section 15: "YES (Audited)").
 */
export default function AdminUsers() {
  const toast = useToast();
  const { role } = useProfile();

  const [search, setSearch] = useState('');
  const [detail, setDetail] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const canFreeze = ['L2_RISK_RECON', 'L3_SUPER_ADMIN'].includes(role);

  const { data, loading, refetch } = useFetch(
    () => endpoints.admin.users(search ? `?search=${encodeURIComponent(search)}` : ''),
    [search],
  );

  async function open(row) {
    try {
      const response = await endpoints.admin.user(row.user_id);
      setDetail(response.data);
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function act(action, message) {
    if (!reason.trim()) {
      toast.error('A reason is required — it goes into the audit trail.');
      return;
    }

    setBusy(true);
    try {
      await action();
      toast.success(message);
      setDetail(null);
      setReason('');
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  const columns = [
    {
      key: 'name',
      label: 'Member',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{row.full_name || '—'}</p>
          <p className="money text-2xs text-slate">{row.masked_phone}</p>
        </div>
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
      key: 'kyc_tier',
      label: 'KYC',
      render: (row) => (
        <Badge tone={row.kyc_tier === 'NONE' ? 'neutral' : 'good'}>{row.kyc_tier}</Badge>
      ),
    },
    {
      key: 'created_on',
      label: 'Joined',
      render: (row) => <span className="text-2xs text-slate">{date(row.created_on)}</span>,
    },
    {
      key: 'last_login',
      label: 'Last seen',
      render: (row) => (
        <span className="text-2xs text-slate">
          {row.last_login ? date(row.last_login) : 'Never'}
        </span>
      ),
    },
  ];

  return (
    <div>
      <AdminHeader
        title="Members"
        subtitle="Search by phone, name or transaction UTR."
      />

      <div className="mb-4 w-full sm:w-96">
        <Input
          placeholder="Phone, name, or UTR"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {loading ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          columns={columns}
          rows={(data || []).map((row) => ({ ...row, id: row.user_id }))}
          empty="No members match that search."
          onRowClick={open}
        />
      )}

      <Sheet
        open={Boolean(detail)}
        onClose={() => {
          setDetail(null);
          setReason('');
        }}
        title={detail?.full_name || 'Member'}
        footer={
          detail && canFreeze && (
            <div className="space-y-2">
              {detail.status === 'FROZEN' ? (
                <Button
                  variant="mint"
                  size="lg"
                  full
                  loading={busy}
                  onClick={() =>
                    act(
                      () => endpoints.admin.unfreeze(detail.user_id, reason),
                      'Account reactivated.',
                    )
                  }
                >
                  Unfreeze account
                </Button>
              ) : (
                <Button
                  variant="danger"
                  size="lg"
                  full
                  loading={busy}
                  onClick={() =>
                    act(
                      () => endpoints.admin.freeze(detail.user_id, reason),
                      'Account frozen.',
                    )
                  }
                >
                  Freeze account
                </Button>
              )}
            </div>
          )
        }
      >
        {detail && (
          <div className="space-y-4 pb-2">
            {detail.viewer_can_see_pii && (
              <div className="rounded-lg bg-amber-50 px-3 py-2">
                <p className="text-2xs leading-relaxed text-amber-900">
                  You are viewing unmasked personal data. This access has been
                  logged against your account.
                </p>
              </div>
            )}

            <Card className="divide-y divide-line py-1">
              <Row label="Phone" value={detail.phone} mono />
              {detail.email && <Row label="Email" value={detail.email} />}
              <Row label="Status" value={statusLabel(detail.status)} />
              <Row label="KYC tier" value={detail.kyc_tier} />
              <Row label="KYC status" value={statusLabel(detail.kyc_status)} />
              <Row label="Joined" value={date(detail.created_on)} />
              {detail.profile?.pan_last4 && (
                <Row label="PAN" value={`••••••${detail.profile.pan_last4}`} mono />
              )}
            </Card>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-line p-3">
                <p className="text-2xs uppercase tracking-wider text-slate">Paid</p>
                <p className="money mt-1 text-lg font-bold text-ink">
                  {money(detail.stats.total_paid)}
                </p>
                <p className="text-2xs text-slate">
                  {detail.stats.successful_payments} payments
                </p>
              </div>
              <div className="rounded-xl border border-line p-3">
                <p className="text-2xs uppercase tracking-wider text-slate">Instruments</p>
                <p className="money mt-1 text-lg font-bold text-ink">
                  {detail.stats.cards_linked}
                </p>
                <p className="text-2xs text-slate">
                  {detail.stats.verified_accounts} verified accounts
                </p>
              </div>
            </div>

            {detail.cards?.length > 0 && (
              <Card className="py-1">
                <p className="px-1 py-2 text-2xs font-semibold uppercase tracking-wider text-slate">
                  Cards
                </p>
                <div className="divide-y divide-line">
                  {detail.cards.map((card) => (
                    <div key={card.card_id} className="flex items-center justify-between py-2.5">
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-ink">{card.issuer_bank}</p>
                        <p className="money text-2xs text-slate">{card.masked_pan}</p>
                      </div>
                      <Badge tone={statusTone(card.status)}>{statusLabel(card.status)}</Badge>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {detail.bank_accounts?.length > 0 && (
              <Card className="py-1">
                <p className="px-1 py-2 text-2xs font-semibold uppercase tracking-wider text-slate">
                  Bank accounts
                </p>
                <div className="divide-y divide-line">
                  {detail.bank_accounts.map((account) => (
                    <div
                      key={account.bank_account_id}
                      className="flex items-center justify-between py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-ink">{account.bank_name}</p>
                        <p className="money text-2xs text-slate">
                          {account.masked_account}
                          {account.name_match_score != null &&
                            ` · ${account.name_match_score}% match`}
                        </p>
                      </div>
                      <Badge tone={statusTone(account.penny_drop_status)}>
                        {statusLabel(account.penny_drop_status)}
                      </Badge>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {canFreeze && (
              <div>
                <span className="mb-1.5 block text-sm font-medium text-ink">
                  Reason <span className="text-slate">(required for any action)</span>
                </span>
                <textarea
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Why are you freezing or reactivating this account?"
                  className="w-full rounded-xl border border-line bg-canvas p-3 text-sm outline-none focus:border-ink/40"
                />
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  );
}
