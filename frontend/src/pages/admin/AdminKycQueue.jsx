import { useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Row, Sheet, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { dateTime, statusLabel, statusTone } from '../../utils/format';
import { AdminHeader, DataTable } from './AdminLayout';

/**
 * KYC review queue (PRD 16.1).
 *
 * Approval is the single gate on a user's transfer limits, so the decision is
 * deliberate: a rejection cannot be submitted without a reason, and that reason
 * is shown to the user verbatim.
 */
export default function AdminKycQueue() {
  const toast = useToast();
  const { role } = useProfile();

  const { data, loading, refetch } = useFetch(() => endpoints.admin.kycQueue(), []);

  const [selected, setSelected] = useState(null);
  const [tier, setTier] = useState('MINIMUM');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const canReview = ['L2_RISK_RECON', 'L3_SUPER_ADMIN'].includes(role);

  async function review(decision) {
    if (decision === 'REJECT' && !reason.trim()) {
      toast.error('A reason is required when rejecting a submission.');
      return;
    }

    setBusy(true);
    try {
      const response = await endpoints.admin.reviewKyc(selected.kyc_id, {
        decision,
        tier: decision === 'APPROVE' ? tier : undefined,
        reason: reason.trim() || undefined,
      });

      toast.success(response.message);
      setSelected(null);
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
      label: 'Applicant',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{row.verified_legal_name || '—'}</p>
          <p className="money text-2xs text-slate">{row.masked_phone}</p>
        </div>
      ),
    },
    {
      key: 'requested_tier',
      label: 'Requested',
      render: (row) => <Badge tone="neutral">{row.requested_tier}</Badge>,
    },
    {
      key: 'documents',
      label: 'Documents',
      render: (row) => (
        <div className="flex gap-1.5">
          {row.has_pan_document && <Badge tone="good">PAN</Badge>}
          {row.has_aadhaar_document && <Badge tone="good">Aadhaar</Badge>}
        </div>
      ),
    },
    {
      key: 'waiting_hours',
      label: 'Waiting',
      render: (row) => (
        <span
          className={cx(
            'money text-sm',
            row.waiting_hours > 24 ? 'font-semibold text-alert' : 'text-slate',
          )}
        >
          {row.waiting_hours != null ? `${row.waiting_hours}h` : '—'}
        </span>
      ),
    },
    {
      key: 'kyc_status',
      label: 'Status',
      render: (row) => (
        <Badge tone={statusTone(row.kyc_status)} dot>
          {statusLabel(row.kyc_status)}
        </Badge>
      ),
    },
  ];

  return (
    <div>
      <AdminHeader
        title="KYC queue"
        subtitle={
          data ? `${data.length} submission${data.length === 1 ? '' : 's'} awaiting review` : undefined
        }
      />

      {loading ? (
        <Skeleton className="h-64 w-full rounded-2xl" />
      ) : (
        <DataTable
          columns={columns}
          rows={(data || []).map((row) => ({ ...row, id: row.kyc_id }))}
          empty="No submissions are waiting. Nice."
          onRowClick={canReview ? (row) => {
            setSelected(row);
            setTier(row.requested_tier || 'MINIMUM');
          } : undefined}
        />
      )}

      {!canReview && (
        <p className="mt-3 text-xs text-slate">
          Reviewing submissions requires L2 Risk or L3 Super Admin access.
        </p>
      )}

      <Sheet
        open={Boolean(selected)}
        onClose={() => {
          setSelected(null);
          setReason('');
        }}
        title="Review submission"
        footer={
          selected && (
            <div className="flex gap-2">
              <Button
                variant="danger"
                size="lg"
                full
                loading={busy}
                onClick={() => review('REJECT')}
              >
                Reject
              </Button>
              <Button
                variant="mint"
                size="lg"
                full
                loading={busy}
                onClick={() => review('APPROVE')}
              >
                Approve
              </Button>
            </div>
          )
        }
      >
        {selected && (
          <div className="space-y-4 pb-2">
            <Card className="divide-y divide-line py-1">
              <Row label="Legal name" value={selected.verified_legal_name} />
              <Row label="Phone" value={selected.masked_phone} mono />
              <Row label="Requested tier" value={selected.requested_tier} />
              <Row label="Submitted" value={dateTime(selected.submitted_at)} />
              <Row
                label="PAN document"
                value={selected.has_pan_document ? 'Uploaded' : 'Missing'}
                tone={selected.has_pan_document ? 'good' : 'alert'}
              />
              <Row
                label="Aadhaar document"
                value={selected.has_aadhaar_document ? 'Uploaded' : 'Not provided'}
              />
            </Card>

            <div>
              <span className="mb-2 block text-sm font-medium text-ink">Grant tier</span>
              <div className="grid grid-cols-2 gap-2">
                {['MINIMUM', 'FULL'].map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setTier(option)}
                    disabled={option === 'FULL' && !selected.has_aadhaar_document}
                    className={cx(
                      'rounded-xl border px-3 py-2.5 text-sm font-medium transition',
                      tier === option
                        ? 'border-mint bg-mint-50 text-ink'
                        : 'border-line text-slate hover:border-ink/20',
                      option === 'FULL' && !selected.has_aadhaar_document && 'cursor-not-allowed opacity-40',
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
              {!selected.has_aadhaar_document && (
                <p className="mt-1.5 text-2xs text-slate">
                  Full KYC needs an Aadhaar document.
                </p>
              )}
            </div>

            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink">
                Reason <span className="text-slate">(required to reject)</span>
              </span>
              <textarea
                rows={3}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Shown to the applicant verbatim, so make it actionable."
                className="w-full rounded-xl border border-line bg-canvas p-3 text-sm outline-none focus:border-ink/30 focus:ring-2 focus:ring-mint/30"
              />
            </div>

            <p className="rounded-lg bg-mist px-3 py-2 text-2xs leading-relaxed text-slate">
              This decision is written to the audit trail with your user id, and
              approval immediately changes what this member can transfer.
            </p>
          </div>
        )}
      </Sheet>
    </div>
  );
}
