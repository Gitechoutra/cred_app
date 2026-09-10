import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { confirmTransfer } from '../../../api/transfers';
import Button from '../../../components/Button';
import ErrorNotice from '../../../components/ErrorNotice';
import Panel from '../../../components/Panel';
import StatusPill from '../../../components/StatusPill';
import TransferTimeline from '../../../components/TransferTimeline';
import useTransferStatus from '../../../hooks/useTransferStatus';
import { money } from '../../../utils/money';

/**
 * Where the 3DS challenge lands (PRD FR-006 steps 6-9).
 *
 * Cashfree returns the user here with `?transfer_id=…`. This screen does two
 * things, in order:
 *
 * 1. Calls `confirm` once. That is belt and braces alongside the webhook -
 *    whichever reaches the backend first resolves the transfer and the second
 *    is a no-op. It proves nothing on its own; the backend re-reads the order
 *    from Cashfree before it moves any money.
 *
 * 2. Polls until the transfer is terminal, because the IMPS payout is
 *    asynchronous and may be retried three times before the circuit breaker
 *    refunds the card.
 *
 * The copy rule from version1.md 3.2 applies throughout: state the cause and
 * the next action, never scold. A reversal is not the user's fault and the
 * screen says their money is coming back.
 */

export default function TransferStatus() {
  const params = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // The route param wins; the query string is how Cashfree hands us back.
  const transferId = params.transferId || searchParams.get('transfer_id');

  const [confirmError, setConfirmError] = useState(null);
  const [confirming, setConfirming] = useState(Boolean(transferId));
  const confirmedRef = useRef(false);

  const { transfer, loading, error, settled, refresh } = useTransferStatus(transferId);

  useEffect(() => {
    if (!transferId || confirmedRef.current) return;
    confirmedRef.current = true;

    (async () => {
      try {
        await confirmTransfer(transferId);
      } catch (cause) {
        // A failed confirm is not a failed transfer - the webhook may already
        // have resolved it. Keep polling and let the real status speak.
        setConfirmError(cause);
      } finally {
        setConfirming(false);
        refresh();
      }
    })();
  }, [transferId, refresh]);

  if (!transferId) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <Panel title="Transfer not found">
          <p className="text-sm text-slate">
            We could not tell which transfer this is. Check your transfer history.
          </p>
          <Button className="mt-4" variant="secondary" onClick={() => navigate('/transfers')}>
            View transfers
          </Button>
        </Panel>
      </div>
    );
  }

  if ((loading || confirming) && !transfer) {
    return (
      <div className="mx-auto max-w-lg p-6 text-center">
        <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-mint border-t-transparent" />
        <p className="mt-4 text-sm text-slate">Confirming your transfer…</p>
        <p className="mt-1 text-xs text-slate">Please do not close this page.</p>
      </div>
    );
  }

  if (!transfer) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorNotice error={error || confirmError} />
      </div>
    );
  }

  const headline = HEADLINES[transfer.status] || {
    title: 'Transfer in progress',
    body: 'We are still processing this transfer.',
  };

  return (
    <div className="mx-auto max-w-lg p-6">
      <header className="mb-6 text-center">
        <StatusPill status={transfer.status} />
        <h1 className="mt-3 text-2xl font-semibold text-ink">{headline.title}</h1>
        <p className="mt-1 text-sm text-slate">{headline.body}</p>

        <p className="tabular mt-5 text-4xl font-semibold text-ink">
          {money(transfer.net_payout_amount)}
        </p>
        <p className="mt-1 text-sm text-slate">
          to {transfer.destination?.bank_name} {transfer.destination?.masked_account}
        </p>
      </header>

      {!settled && (
        <p className="mb-4 text-center text-xs text-slate">
          This updates automatically. You can safely leave this page.
        </p>
      )}

      {transfer.failure_reason && transfer.status !== 'SUCCEEDED' && (
        <div className="mb-5 rounded-xl border border-line bg-mist p-4">
          <p className="text-sm text-ink">{transfer.failure_reason}</p>
        </div>
      )}

      <Panel title="Progress" className="mb-5">
        <TransferTimeline steps={transfer.timeline} />
      </Panel>

      <Panel title="Details">
        <dl className="space-y-3 text-sm">
          <Detail label="Sent from" value={transfer.card?.masked_pan} />
          <Detail label="Charged to card" value={money(transfer.total_charged_to_card)} />
          <Detail label="Fee + GST" value={money(
            (transfer.convenience_fee || 0) + (transfer.gst_on_fee || 0),
          )} />
          {transfer.utr && <Detail label="Bank reference (UTR)" value={transfer.utr} />}
          <Detail label="Reference" value={transfer.transfer_id?.slice(0, 8).toUpperCase()} />
        </dl>
      </Panel>

      <div className="mt-6 flex gap-3">
        <Button variant="secondary" className="flex-1" onClick={() => navigate('/transfers')}>
          View all transfers
        </Button>
        {transfer.status === 'SUCCEEDED' && (
          <Button
            variant="primary"
            className="flex-1"
            onClick={() => navigate(`/transfer/${transfer.transfer_id}/receipt`)}
          >
            Receipt
          </Button>
        )}
      </div>
    </div>
  );
}

const HEADLINES = {
  SUCCEEDED: {
    title: 'Transfer complete',
    body: 'The money has been credited to your bank account.',
  },
  PAYOUT_PROCESSING: {
    title: 'On its way',
    body: 'Your card was charged and the money is being sent to your bank.',
  },
  INBOUND_CHARGED: {
    title: 'On its way',
    body: 'Your card was charged and the money is being sent to your bank.',
  },
  AUTH_PENDING: {
    title: 'Waiting for authentication',
    body: 'Complete the verification with your bank to continue.',
  },
  REVERSED_TO_CARD: {
    title: 'Refunded to your card',
    body: 'We could not complete the transfer, so the full amount has been returned to your card. It usually appears within 5–7 working days.',
  },
  REVERSAL_INIT: {
    title: 'Refunding your card',
    body: 'The transfer could not be completed. We are returning the full amount to your card.',
  },
  PENDING_RECONCILIATION: {
    title: 'Under review',
    body: 'This transfer needs a manual check. Our team is on it and will update you.',
  },
  RISK_FAILED: {
    title: 'Could not proceed',
    body: 'This transfer did not pass our security checks. Nothing was charged.',
  },
  FAILED: {
    title: 'Did not complete',
    body: 'The transfer did not go through. No funds were debited.',
  },
};

function Detail({ label, value }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-slate">{label}</dt>
      <dd className="tabular text-ink">{value}</dd>
    </div>
  );
}
