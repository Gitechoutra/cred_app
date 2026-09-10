import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import Button from '../../../components/Button';
import Panel from '../../../components/Panel';

/**
 * The stand-in 3DS screen for simulated adapters.
 *
 * When the backend runs with `USE_SANDBOX_ADAPTERS=True` there are no Cashfree
 * credentials, so `create_payment_order` returns a local `checkout_url` instead
 * of a payment session. This page is what that URL points at.
 *
 * It exists so the full authorise -> confirm -> settle -> notify path can be
 * walked before any vendor contract is signed - which matters, because all nine
 * PRD section 21 integrations are still marked "To Be Confirmed" and the
 * transfer merchant model is an open legal question. It is deliberately styled
 * as an obvious simulation: nobody should ever mistake this for a real issuer
 * page, and it is unreachable once real credentials are configured.
 */

export default function SandboxChallenge() {
  const { transferId } = useParams();
  const navigate = useNavigate();
  const [working, setWorking] = useState(false);

  function approve() {
    setWorking(true);
    // The status screen calls confirm, which re-reads the (simulated) gateway
    // and walks the transfer through exactly the same engine path as a real one.
    navigate(`/transfer/status?transfer_id=${transferId}`);
  }

  return (
    <div className="mx-auto max-w-lg p-6">
      <div className="mb-4 rounded-xl border border-warn/30 bg-warn/5 p-3">
        <p className="text-sm font-semibold text-warn">Simulated authentication</p>
        <p className="mt-1 text-xs text-slate">
          No real bank is involved and no money moves. This screen stands in for
          the 3DS challenge while CashU runs on sandbox adapters.
        </p>
      </div>

      <Panel title="Verify your payment" subtitle="Your bank would normally ask for an OTP here.">
        <dl className="space-y-3 text-sm">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-slate">Transfer</dt>
            <dd className="tabular text-ink">
              {transferId?.slice(0, 8).toUpperCase()}
            </dd>
          </div>
        </dl>

        <div className="mt-6 space-y-3">
          <Button variant="primary" className="w-full" loading={working} onClick={approve}>
            Approve payment
          </Button>
          <Button
            variant="ghost"
            className="w-full"
            disabled={working}
            onClick={() => navigate('/transfer')}
          >
            Cancel
          </Button>
        </div>

        <p className="mt-4 text-xs text-slate">
          Cancelling leaves the transfer awaiting authentication. Nothing has been
          charged.
        </p>
      </Panel>
    </div>
  );
}
