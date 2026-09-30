import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Timeline } from '../../components/domain';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Row, Skeleton, cx } from '../../components/ui';
import { ErrorCard, StatusHero } from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime, money } from '../../utils/format';
import { CategoryIcon, billStatus, downloadReceipt } from './PayBillsUI';

/**
 * One Pay Bills request: the result screen straight after the OTP, and the
 * transaction detail page History opens.
 *
 * The status is the server's, never assumed. Straight after the OTP a payout
 * that is still in flight shows the processing screen and is polled; only a
 * status the backend reports as final changes what is shown. A payout still
 * unconfirmed after the polling window becomes the pending screen, and the
 * scheduler settles it later.
 */

const IN_FLIGHT = ['PROCESSING', 'PENDING'];
const POLL_MS = 2000;
const POLL_TRIES = 6;

export default function PayBillStatus() {
  const { billPaymentId } = useParams();
  const { state } = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const fresh = Boolean(state?.fresh);

  const [bill, setBill] = useState(state?.bill || null);
  const [polling, setPolling] = useState(fresh && IN_FLIGHT.includes(state?.bill?.status));
  const [showDetails, setShowDetails] = useState(!fresh);
  const tries = useRef(0);

  const { data, loading, error, refetch } = useFetch(
    () => endpoints.billPay.get(billPaymentId), [billPaymentId],
  );

  useEffect(() => { if (data) setBill(data); }, [data]);

  // Straight after the OTP: keep asking while the payout is in flight.
  useEffect(() => {
    if (!polling) return undefined;
    if (bill && !IN_FLIGHT.includes(bill.status)) { setPolling(false); return undefined; }
    if (tries.current >= POLL_TRIES) { setPolling(false); return undefined; }
    const timer = setTimeout(async () => {
      tries.current += 1;
      try {
        const res = await endpoints.billPay.get(billPaymentId, { background: true });
        setBill(res.data);
      } catch {
        /* keep the last known state; the next tick or the scheduler will settle it */
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [polling, bill, billPaymentId]);

  // A completed request has nothing left in the form to resume.
  useEffect(() => {
    if (bill?.status === 'SUCCEEDED') {
      try { sessionStorage.removeItem('cashu.draft.pay-bills'); } catch { /* ignore */ }
    }
  }, [bill?.status]);

  if (!bill && loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay Bills" back="/transactions" />
        <Skeleton className="h-64 w-full rounded-3xl" />
        <Skeleton className="mt-4 h-72 w-full rounded-2xl" />
      </div>
    );
  }

  if (!bill) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay Bills" back="/transactions" />
        <ErrorCard error={error} title="We could not find this payment" onRetry={refetch} />
      </div>
    );
  }

  /* ── Processing ─────────────────────────────────────────────────────── */
  if (polling && IN_FLIGHT.includes(bill.status)) {
    return <Processing bill={bill} />;
  }

  const home = () => navigate('/home');
  const receipt = () => {
    if (!downloadReceipt(bill)) toast.error('Allow pop-ups to download the receipt.');
  };

  const hero = {
    SUCCEEDED: {
      kind: 'success',
      title: 'Payment Successful ✓',
      subtitle: `${money(bill.bill_amount)} payment request has been processed successfully.`,
    },
    FAILED: {
      kind: 'failure',
      title: 'Payment could not be completed',
      subtitle: bill.failure_reason,
    },
    PENDING: {
      kind: 'pending',
      title: 'Payment is being processed',
      subtitle: 'Your transaction is currently under processing. We will update the status once processing is complete.',
    },
    PROCESSING: {
      kind: 'pending',
      title: 'Payment is being processed',
      subtitle: 'Your transaction is currently under processing. We will update the status once processing is complete.',
    },
    REVERSED: {
      kind: 'cancelled',
      title: 'Payment reversed',
      subtitle: bill.failure_reason || 'Your bank returned this payment.',
    },
    CANCELLED: { kind: 'cancelled', title: 'Request cancelled', subtitle: 'Nothing was charged.' },
    EXPIRED: { kind: 'cancelled', title: 'Request expired', subtitle: 'It was not verified in time. Nothing was charged.' },
    AWAITING_OTP: { kind: 'pending', title: 'Waiting for OTP', subtitle: 'This request has not been verified yet.' },
  }[bill.status] || { kind: 'pending', title: billStatus(bill.status).label };

  const restored = ['FAILED', 'REVERSED'].includes(bill.status) && bill.otp_verified_at && bill.available_after != null;

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader title={fresh ? '' : 'Bill payment'} back={fresh ? undefined : '/transactions'} />

      <Card className="p-6 sm:p-8">
        <StatusHero
          kind={hero.kind}
          title={hero.title}
          subtitle={hero.subtitle}
          amount={money(bill.bill_amount)}
          amountTone={bill.status === 'FAILED' ? 'text-slate line-through decoration-2' : undefined}
        />
        {restored && (
          <p className="mx-auto mt-3 max-w-xs rounded-xl bg-mint-50 px-3 py-2 text-center text-xs font-medium text-mint-800">
            {money(bill.total_amount)} has been restored to your available credit - fee and GST included.
          </p>
        )}

        <div className="mt-6 divide-y divide-line rounded-2xl border border-line px-4 py-1">
          <Row label="Transaction ID" value={bill.reference} mono />
          <Row label="Bill" value={bill.category_label} />
          <Row label="Bank" value={bill.bank} />
          <Row label="Amount" value={money(bill.bill_amount)} mono />
          <Row label="Credit Utilized" value={money(bill.total_amount)} mono />
          <Row label="Date & Time" value={dateTime(bill.completed_at || bill.created_on)} />
        </div>

        <div className="mt-6 space-y-2.5">
          {bill.status === 'SUCCEEDED' && (
            <>
              <Button variant="mint" size="lg" full onClick={() => setShowDetails((v) => !v)}>
                {showDetails ? 'Hide transaction' : 'View Transaction'}
              </Button>
              <div className="grid grid-cols-2 gap-2.5">
                <Button variant="outline" size="md" onClick={receipt}>Download Receipt</Button>
                <Button variant="outline" size="md" onClick={home}>Back to Home</Button>
              </div>
            </>
          )}

          {bill.status === 'FAILED' && (
            <div className="grid grid-cols-2 gap-2.5">
              <Button variant="mint" size="lg" onClick={() => navigate('/pay-bills?step=summary')}>Try Again</Button>
              <Button variant="outline" size="lg" onClick={home}>Back to Home</Button>
            </div>
          )}

          {IN_FLIGHT.includes(bill.status) && (
            <>
              <Button
                variant="mint"
                size="lg"
                full
                onClick={async () => { setShowDetails(true); await refetch(); }}
              >
                View Transaction Status
              </Button>
              <Button variant="outline" size="md" full onClick={home}>Back to Home</Button>
            </>
          )}

          {!['SUCCEEDED', 'FAILED', ...IN_FLIGHT].includes(bill.status) && (
            <div className="grid grid-cols-2 gap-2.5">
              <Button variant="outline" size="md" onClick={receipt}>Download Receipt</Button>
              <Button variant="mint" size="md" onClick={home}>Back to Home</Button>
            </div>
          )}
        </div>
      </Card>

      {showDetails && <Details bill={bill} />}
    </div>
  );
}

/* ── Processing ─────────────────────────────────────────────────────────── */

function Processing({ bill }) {
  return (
    <div className="mx-auto grid min-h-[60vh] w-full max-w-md place-items-center" role="status" aria-live="polite">
      <div className="w-full text-center">
        <span className="relative mx-auto grid h-24 w-24 place-items-center">
          <span className="absolute inset-0 rounded-full bg-mint/20 motion-safe:animate-pulse-ring" />
          <span className="absolute inset-2 rounded-full border-2 border-mint/25 border-t-mint-600 motion-safe:animate-spin" />
          {/* Credit -> bank, drawn as a card sliding toward a bank. */}
          <svg viewBox="0 0 48 48" className="relative h-10 w-10 text-ink" fill="none" aria-hidden="true">
            <rect x="5" y="14" width="18" height="12" rx="2.5" stroke="currentColor" strokeWidth="2.2" />
            <path d="M5 18.5h18" stroke="currentColor" strokeWidth="2.2" />
            <path d="M27 20h8m-3-3l3 3-3 3" stroke="#00B386" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className="motion-safe:animate-pulse" />
            <path d="M37 24l5-3 5 3M38 25v7m4-7v7m4-7v7M37 33h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" transform="translate(-4 0)" />
          </svg>
        </span>
        <h1 className="mt-6 text-xl font-bold tracking-tight text-ink">Processing Payment</h1>
        <p className="mx-auto mt-1.5 max-w-xs text-sm text-slate">
          We&apos;re processing your bill payment request. Please don&apos;t close this page.
        </p>

        <Card className="mt-6 divide-y divide-line py-1 text-left">
          <Row label="Amount" value={money(bill.bill_amount)} mono />
          <Row label="Destination bank" value={bill.bank} />
          <Row label="Transaction reference" value={bill.reference} mono />
        </Card>
      </div>
    </div>
  );
}

/* ── Details ────────────────────────────────────────────────────────────── */

function Details({ bill }) {
  const status = billStatus(bill.status);
  return (
    <div className="mt-4 space-y-4 animate-fade-up">
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-mist text-ink">
            <CategoryIcon category={bill.category} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-bold text-ink">{bill.category_label} Bill</p>
            <p className="truncate text-2xs text-slate">Credit → Bank</p>
          </div>
          <Badge tone={status.tone} dot>{status.label}</Badge>
        </div>

        <div className="divide-y divide-line">
          <Row label="Bill provider" value={bill.provider} />
          <Row label="Bill/reference number" value={bill.bill_reference} mono />
          <Row label="Purpose" value={bill.purpose_label} />
          {bill.purpose_note && <Row label="Description" value={bill.purpose_note} />}
          <Row label="Bill amount" value={money(bill.bill_amount)} mono />
          <Row label={`Processing fee (${bill.fee_percent}%)`} value={money(bill.fee_amount)} mono />
          <Row label="GST on fee" value={money(bill.gst_amount)} mono />
          <Row label="Total credit utilised" value={money(bill.total_amount)} mono />
          <Row label="Paid to" value={bill.bank} />
          {bill.utr && <Row label="Bank UTR" value={bill.utr} mono />}
          <Row label="Transaction ID" value={bill.reference} mono />
          <Row label="Requested" value={dateTime(bill.created_on)} />
        </div>
      </Card>

      {bill.failure_reason && ['FAILED', 'REVERSED'].includes(bill.status) && (
        <div className={cx('rounded-xl border p-3.5',
          bill.status === 'FAILED' ? 'border-red-200 bg-red-50' : 'border-line bg-mist/60')}
        >
          <p className={cx('text-xs font-semibold', bill.status === 'FAILED' ? 'text-alert' : 'text-ink')}>
            {bill.status === 'FAILED' ? 'Why this failed' : 'Why this was reversed'}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate">{bill.failure_reason}</p>
        </div>
      )}

      <Card className="p-5">
        <p className="mb-4 text-2xs font-semibold uppercase tracking-wider text-slate">Status</p>
        <Timeline steps={bill.timeline} />
      </Card>

      <p className="px-2 text-center text-2xs leading-relaxed text-slate">
        Declaration accepted {dateTime(bill.consent_at)} · disclosure {bill.disclosure_version}.
        Quote the transaction ID to support for any query.
      </p>
    </div>
  );
}
