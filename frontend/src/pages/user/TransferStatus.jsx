import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Timeline } from '../../components/domain';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Row, Skeleton, Loader3D, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { dateTime, money, statusLabel } from '../../utils/format';

const TERMINAL = ['SUCCEEDED', 'REVERSED_TO_CARD', 'FAILED', 'RISK_FAILED'];

/**
 * Transfer outcome (PRD FR-006, section 9.3).
 *
 * This screen is the app's one deliberate "moment" - the transfer is the thing
 * users come to CashU for, and the success state is the only place motion is
 * allowed to be celebratory.
 *
 * It also polls. A transfer that is charged but not yet settled resolves in the
 * background through the payout retry ladder, and a user staring at
 * "processing" needs it to update itself rather than asking them to refresh.
 */
export default function TransferStatus() {
  const { transferId } = useParams();
  const { state } = useLocation();
  const navigate = useNavigate();
  const toast = useToast();

  const [transfer, setTransfer] = useState(state?.transfer || null);
  const [loading, setLoading] = useState(!state?.transfer);
  const [confirming, setConfirming] = useState(false);

  const pollTimer = useRef();
  const confirmed = useRef(false);

  const load = useCallback(async () => {
    try {
      const response = await endpoints.transfers.get(transferId);
      setTransfer(response.data);
      return response.data;
    } catch (err) {
      toast.error(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [transferId, toast]);

  /**
   * Complete the charge once the user returns from authentication.
   *
   * Guarded by a ref rather than state: React 18 StrictMode mounts effects
   * twice in development, and confirming a charge twice is not something to
   * leave to chance even though the backend is idempotent.
   */
  const confirm = useCallback(async () => {
    if (confirmed.current) return;
    confirmed.current = true;

    setConfirming(true);
    try {
      const response = await endpoints.transfers.confirm(transferId);
      setTransfer(response.data);

      if (response.data.status === 'SUCCEEDED') {
        toast.success('Transfer completed.');
      }
    } catch (err) {
      toast.error(err.message);
      await load();
    } finally {
      setConfirming(false);
      setLoading(false);
    }
  }, [transferId, toast, load]);

  useEffect(() => {
    if (state?.justInitiated) {
      confirm();
    } else {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while the transfer is still in flight.
  useEffect(() => {
    if (!transfer || TERMINAL.includes(transfer.status)) {
      clearTimeout(pollTimer.current);
      return undefined;
    }

    pollTimer.current = setTimeout(load, 4000);
    return () => clearTimeout(pollTimer.current);
  }, [transfer, load]);

  if (loading || (!transfer && confirming)) {
    return (
      <div className="grid min-h-screen place-items-center bg-canvas px-6">
        <div className="flex flex-col items-center text-center">
          <Loader3D size="large" />
          <p className="mt-4 text-sm font-medium text-ink">Completing your transfer</p>
          <p className="mt-1 text-xs text-slate">Please do not close this screen.</p>
        </div>
      </div>
    );
  }

  if (!transfer) {
    return (
      <div className="">
        <PageHeader title="Transfer" back="/home" />
        <div className="px-4 pt-8">
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  const succeeded = transfer.status === 'SUCCEEDED';
  const reversed = transfer.status === 'REVERSED_TO_CARD';
  const failed = ['FAILED', 'RISK_FAILED'].includes(transfer.status);
  const inFlight = !TERMINAL.includes(transfer.status);

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="" back="/home" />

        {/* ── Outcome ─────────────────────────────────────────────────── */}
        <section className="px-6 pt-6 text-center">
          <StatusMark succeeded={succeeded} reversed={reversed} failed={failed} inFlight={inFlight} />

          <h1 className="mt-5 text-2xl font-bold tracking-tight text-ink">
            {succeeded && 'Transfer complete'}
            {reversed && 'Refunded to your card'}
            {failed && 'Transfer not completed'}
            {inFlight && 'Sending to your bank'}
          </h1>

          <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-slate">
            {succeeded && `${money(transfer.net_payout_amount)} is on its way to ${transfer.destination.bank_name}.`}
            {reversed && 'We could not reach your bank, so the full amount has been reversed to your card. It usually appears within 2 working days.'}
            {failed && (transfer.failure_reason || 'No funds were debited from your card.')}
            {inFlight && 'Your card has been charged and the money is being sent. This usually takes under a minute.'}
          </p>

          {succeeded && (
            <p className="money mt-6 text-[2.5rem] font-bold leading-none tracking-tight text-ink animate-scale-in">
              {money(transfer.net_payout_amount)}
            </p>
          )}
        </section>

        {/* ── Progress ────────────────────────────────────────────────── */}
        {transfer.timeline && (
          <div className="mt-8 px-5">
            <Card>
              <Timeline steps={transfer.timeline} />
            </Card>
          </div>
        )}

        {/* ── Detail ──────────────────────────────────────────────────── */}
        <div className="mt-4 px-5">
          <Card className="divide-y divide-line py-1">
            <Row label="Status" value={statusLabel(transfer.status)} />
            <Row label="From" value={transfer.card.masked_pan} mono />
            <Row
              label="To"
              value={`${transfer.destination.bank_name} ${transfer.destination.masked_account}`}
            />
            <Row label="Amount sent" value={money(transfer.net_payout_amount)} mono />
            <Row label="Convenience fee" value={money(transfer.convenience_fee)} mono />
            <Row label="GST" value={money(transfer.gst_on_fee)} mono />
            <Row
              label="Charged to card"
              value={money(transfer.total_charged_to_card)}
              mono
            />
            {transfer.utr && <Row label="UTR" value={transfer.utr} mono />}
            <Row label="Initiated" value={dateTime(transfer.created_on)} />
          </Card>
        </div>

        {/* ── Actions ─────────────────────────────────────────────────── */}
        <div className="mt-6 space-y-2.5 px-5">
          {succeeded && (
            <Button
              variant="outline"
              size="lg"
              full
              onClick={() => navigate(`/transactions/${transfer.transaction_id}`)}
            >
              View receipt
            </Button>
          )}

          {(failed || reversed) && (
            <Button variant="mint" size="lg" full onClick={() => navigate('/transfer')}>
              Try again
            </Button>
          )}

          <Button
            variant={succeeded ? 'mint' : 'ghost'}
            size="lg"
            full
            onClick={() => navigate('/home')}
          >
            Back to home
          </Button>

          {(failed || reversed) && (
            <button
              type="button"
              onClick={() => navigate('/support')}
              className="w-full py-2 text-center text-sm font-medium text-slate hover:text-ink"
            >
              Contact support
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * The status mark.
 *
 * A drawn ring rather than a static icon: the stroke completing is what makes
 * the success feel earned. Reduced-motion users get the finished state, since
 * the animation carries no information the label does not already give.
 */
function StatusMark({ succeeded, reversed, failed, inFlight }) {
  const tone = succeeded ? 'mint' : failed ? 'alert' : reversed ? 'warn' : 'ink';

  return (
    <div className="relative mx-auto grid h-24 w-24 place-items-center">
      <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full -rotate-90">
        <circle cx="50" cy="50" r="45" fill="none" stroke="#E6EAE8" strokeWidth="5" />
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray="283"
          className={cx(
            'animate-ring-draw',
            tone === 'mint' && 'stroke-mint',
            tone === 'alert' && 'stroke-alert',
            tone === 'warn' && 'stroke-warn',
            tone === 'ink' && 'stroke-ink',
          )}
          style={{ strokeDashoffset: inFlight ? 100 : 0 }}
        />
      </svg>

      <span
        className={cx(
          'grid h-16 w-16 place-items-center rounded-full',
          tone === 'mint' && 'bg-mint text-ink',
          tone === 'alert' && 'bg-red-50 text-alert',
          tone === 'warn' && 'bg-amber-50 text-warn',
          tone === 'ink' && 'bg-mist text-ink',
        )}
      >
        {succeeded && (
          <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none">
            <path
              d="M5 12.5l5 5 9-9"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
        {failed && (
          <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none">
            <path d="M7 7l10 10M17 7L7 17" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
        )}
        {reversed && (
          <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none">
            <path
              d="M4 12a8 8 0 1 1 3 6.2"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
            <path d="M4 8v4.5h4.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
        {inFlight && <Loader3D size="medium" />}
      </span>
    </div>
  );
}
