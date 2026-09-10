import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Meter, Row, Sheet, Skeleton, cx,
} from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money, statusLabel, statusTone } from '../../utils/format';

export default function EmiDetail() {
  const { emiId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: emi, loading, refetch } = useFetch(() => endpoints.emi.get(emiId), [emiId]);

  const [confirmRemove, setConfirmRemove] = useState(false);
  const [working, setWorking] = useState(false);

  async function remove() {
    setWorking(true);
    try {
      await endpoints.emi.remove(emiId);
      toast.success('EMI removed from tracking.');
      navigate('/emi', { replace: true });
    } catch (err) {
      toast.error(err.message);
      setWorking(false);
      setConfirmRemove(false);
    }
  }

  async function toggleMandate(action) {
    setWorking(true);
    try {
      await action();
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return (
      <div className="">
        <PageHeader title="EMI" back="/emi" />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!emi) {
    return (
      <div className="">
        <PageHeader title="EMI" back="/emi" />
        <EmptyState title="EMI not found" />
      </div>
    );
  }

  const overdue = emi.payment_status === 'OVERDUE';
  const mandate = emi.mandate;

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title={emi.nickname || emi.provider_name}
          subtitle={emi.masked_loan_account}
          back="/emi"
        />

        <div className="space-y-4 px-4 pt-4">
          {/* ── Amount ──────────────────────────────────────────────── */}
          <section
            className={cx(
              'rounded-2xl p-5 text-white',
              overdue ? 'bg-alert' : 'bg-ink',
            )}
            style={!overdue && emi.brand_color ? { backgroundColor: emi.brand_color } : undefined}
          >
            <p className="text-xs text-white/60">Monthly EMI</p>
            <p className="money mt-1 text-[2rem] font-bold leading-none">
              {money(emi.emi_amount)}
            </p>

            <div className="mt-4 flex items-end justify-between">
              <div>
                <p className="text-2xs text-white/55">
                  {overdue ? 'Was due' : 'Next due'}
                </p>
                <p className="mt-0.5 text-sm font-semibold">
                  {emi.next_due_date ? date(emi.next_due_date) : 'Loan closed'}
                </p>
              </div>

              {emi.auto_pay_status === 'ACTIVE' && (
                <span className="rounded-full bg-white/20 px-2.5 py-1 text-2xs font-semibold">
                  Auto-pay on
                </span>
              )}
            </div>

            {emi.progress_percentage !== null && emi.progress_percentage !== undefined && (
              <div className="mt-4 border-t border-white/15 pt-4">
                <div className="flex items-center justify-between text-2xs text-white/60">
                  <span>{emi.tenure_paid} paid</span>
                  <span>{emi.tenure_remaining} remaining</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
                  <div
                    className="h-full rounded-full bg-mint transition-all duration-700"
                    style={{ width: `${emi.progress_percentage}%` }}
                  />
                </div>
              </div>
            )}
          </section>

          {/* ── Actions ─────────────────────────────────────────────── */}
          {emi.is_active && (
            <div className="flex gap-2">
              <Button
                variant="mint"
                size="lg"
                full
                onClick={() => navigate(`/emi/${emiId}/pay`)}
              >
                Pay now
              </Button>

              {emi.auto_pay_status === 'NOT_CONFIGURED' && emi.can_enable_autopay && (
                <Button
                  variant="outline"
                  size="lg"
                  full
                  onClick={() => navigate(`/emi/${emiId}/autopay`)}
                >
                  Set up auto-pay
                </Button>
              )}
            </div>
          )}

          {/* ── Manual entry needs verification ─────────────────────── */}
          {emi.is_manually_created && !emi.admin_verified && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5">
              <p className="text-xs font-semibold text-amber-900">
                Verification pending
              </p>
              <p className="mt-1 text-xs leading-relaxed text-amber-900/80">
                You entered these details manually. Upload your loan sanction
                letter so our team can verify them — auto-pay unlocks once that
                is done.
              </p>
            </div>
          )}

          {/* ── Mandate ─────────────────────────────────────────────── */}
          {mandate && (
            <Card>
              <div className="flex items-center justify-between">
                <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                  Auto-pay mandate
                </p>
                <Badge tone={statusTone(mandate.status)} dot>
                  {statusLabel(mandate.status)}
                </Badge>
              </div>

              <div className="mt-3 divide-y divide-line">
                <Row label="Mandate type" value={mandate.mandate_type.replace('_', ' ')} />
                {mandate.umn && <Row label="UMN" value={mandate.umn} mono />}
                <Row label="Debit limit" value={money(mandate.max_amount)} mono />
                {mandate.next_debit_date && (
                  <Row label="Next debit" value={date(mandate.next_debit_date)} />
                )}
              </div>

              <p className="mt-3 rounded-lg bg-mist px-3 py-2 text-2xs leading-relaxed text-slate">
                We notify you 48 hours before every automatic debit, as required by
                RBI. You can pause or cancel up to 24 hours before the debit date.
              </p>

              <div className="mt-3 flex gap-2">
                {mandate.status === 'ACTIVE' && (
                  <Button
                    variant="outline"
                    size="sm"
                    full
                    loading={working}
                    onClick={() =>
                      toggleMandate(() => endpoints.mandates.pause(mandate.mandate_id, 'User paused'))
                    }
                  >
                    Pause
                  </Button>
                )}
                {mandate.status === 'PAUSED' && (
                  <Button
                    variant="mint"
                    size="sm"
                    full
                    loading={working}
                    onClick={() => toggleMandate(() => endpoints.mandates.resume(mandate.mandate_id))}
                  >
                    Resume
                  </Button>
                )}
                {mandate.status === 'PENDING_AFA' && (
                  <Button
                    variant="mint"
                    size="sm"
                    full
                    loading={working}
                    onClick={() =>
                      toggleMandate(() => endpoints.mandates.activate(mandate.mandate_id))
                    }
                  >
                    Complete bank authorisation
                  </Button>
                )}
                {['ACTIVE', 'PAUSED'].includes(mandate.status) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    full
                    loading={working}
                    onClick={() =>
                      toggleMandate(() =>
                        endpoints.mandates.cancel(mandate.mandate_id, 'Cancelled by user'),
                      )
                    }
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </Card>
          )}

          {/* ── Loan detail ─────────────────────────────────────────── */}
          <Card className="divide-y divide-line py-1">
            <Row label="Lender" value={emi.provider_name} />
            <Row label="Loan account" value={emi.masked_loan_account} mono />
            <Row label="Loan type" value={emi.loan_type?.replace(/_/g, ' ')} />
            {emi.total_loan_amount != null && (
              <Row label="Loan amount" value={money(emi.total_loan_amount)} mono />
            )}
            {emi.outstanding_bal != null && (
              <Row label="Outstanding" value={money(emi.outstanding_bal)} mono />
            )}
            {emi.interest_rate != null && (
              <Row label="Interest rate" value={`${emi.interest_rate}%`} mono />
            )}
            <Row label="Due day" value={`${emi.due_day_of_month} of every month`} />
            {emi.last_paid_date && <Row label="Last paid" value={date(emi.last_paid_date)} />}
          </Card>

          {/* ── History ─────────────────────────────────────────────── */}
          {emi.payment_history?.length > 0 && (
            <Card className="py-1">
              <p className="px-1 py-2 text-2xs font-semibold uppercase tracking-wider text-slate">
                Payment history
              </p>

              <div className="divide-y divide-line">
                {emi.payment_history.map((payment) => (
                  <div key={payment.payment_id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="money text-sm font-medium text-ink">
                        {money(payment.amount)}
                      </p>
                      <p className="text-2xs text-slate">
                        {payment.installment_number ? `Installment ${payment.installment_number} · ` : ''}
                        {date(payment.created_on)}
                        {payment.is_auto_pay ? ' · Auto' : ''}
                      </p>
                    </div>

                    <Badge tone={statusTone(payment.status)} className="shrink-0">
                      {statusLabel(payment.status)}
                    </Badge>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Button variant="ghost" size="lg" full onClick={() => setConfirmRemove(true)}>
            Stop tracking this loan
          </Button>
        </div>
      </div>

      <Sheet
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        title="Stop tracking?"
        footer={
          <div className="flex gap-2">
            <Button variant="outline" size="lg" full onClick={() => setConfirmRemove(false)}>
              Keep tracking
            </Button>
            <Button variant="danger" size="lg" full loading={working} onClick={remove}>
              Stop tracking
            </Button>
          </div>
        }
      >
        <p className="pb-2 text-sm leading-relaxed text-slate">
          We will stop reminding you about this EMI and cancel any auto-pay
          mandate. Your loan with {emi.provider_name} is unaffected — you will
          need to pay it directly.
        </p>
      </Sheet>
    </div>
  );
}
