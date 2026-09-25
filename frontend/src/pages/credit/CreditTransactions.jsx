import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import {
  Button, Card, EmptyState, Loader3D, Row, Skeleton, cx,
} from '../../components/ui';
import { CreditTransactionRow } from '../../components/credit/CreditTransactionRow';
import {
  CREDIT_TYPE_LABEL, ErrorCard, StatusHero, TransactionStatusBadge,
  categoryLabel, friendlyError,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useReturnTo } from '../../hooks/useNavHistory';
import { dateTime, money } from '../../utils/format';

/**
 * Everything that has happened on the credit line.
 *
 * Debits and credits are told apart by sign and colour, not only by a type
 * label: a list where a purchase and a refund look identical except for one word
 * is a list people misread. Declined and cancelled rows are listed too, struck
 * through, because "why was my card declined?" deserves an answer on screen.
 *
 * `available_after` is shown per row because it is what the account said at
 * the time. It comes from the stored column rather than a running total
 * computed here - a sum recomputed in the browser would paper over any drift
 * instead of showing it.
 */

// `value`, not `id`: the shared Tabs keys on tab.value.
const TYPES = [
  { value: '', label: 'All' },
  { value: 'PURCHASE', label: 'Payments made' },
  { value: 'PAYMENT', label: 'Bills paid' },
  { value: 'REFUND', label: 'Refunds' },
  { value: 'FEE', label: 'Fees' },
];

const STATUSES = [
  { value: '', label: 'Any status' },
  { value: 'SUCCEEDED', label: 'Successful' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'CANCELLED', label: 'Cancelled' },
  { value: 'REVERSED', label: 'Refunded' },
];

export function CreditTransactionList() {
  const navigate = useNavigate();
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const [rows, setRows] = useState([]);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Guards a slow page-1 answer for an old filter landing after a newer one.
  const request = useRef(0);

  const load = useCallback(async (nextPage, replace) => {
    const ticket = ++request.current;
    if (replace) setLoading(true);
    else setLoadingMore(true);
    setError(null);

    try {
      const response = await endpoints.credit.transactions(
        nextPage, type, status, { background: !replace },
      );
      if (ticket !== request.current) return;
      const items = response.data || [];
      setRows((current) => (replace ? items : [...current, ...items]));
      setPage(nextPage);
      setHasNext(Boolean(response.pagination?.has_next));
    } catch (err) {
      if (ticket === request.current) setError(err);
    } finally {
      if (ticket === request.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [type, status]);

  useEffect(() => {
    load(1, true);
  }, [load]);

  const filtered = Boolean(type || status);

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader title="Transactions" subtitle="Every payment on your card." back="/credit" />

      {/* Scrolls inside itself on a narrow phone rather than squeezing the
          labels or widening the page. */}
      <div className="-mx-1 mb-3 overflow-x-auto px-1 pb-1">
        <div className="flex min-w-max gap-2" role="tablist" aria-label="Transaction type">
          {TYPES.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={type === tab.value}
              onClick={() => setType(tab.value)}
              className={cx(
                'rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-all',
                type === tab.value
                  ? 'border-ink bg-ink text-white shadow-sm'
                  : 'border-line bg-canvas text-slate hover:border-ink/20 hover:text-ink',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4 flex items-center justify-between gap-3">
        <label htmlFor="txn-status" className="text-xs font-medium text-slate">
          Status
        </label>
        <select
          id="txn-status"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-9 min-w-0 max-w-[60%] rounded-xl border border-line bg-canvas px-3 text-sm text-ink outline-none transition focus:border-ink/40 focus:ring-2 focus:ring-mint/20"
        >
          {STATUSES.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <Card className="space-y-3">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </Card>
      ) : error && rows.length === 0 ? (
        <ErrorCard
          error={error}
          title="We could not load your transactions"
          onRetry={() => load(1, true)}
        />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            title={filtered ? 'Nothing matches these filters' : 'No transactions yet'}
            description={
              filtered
                ? 'Try another type or status.'
                : 'Payments you make with your card, and bills you pay, will appear here.'
            }
            action={filtered && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => { setType(''); setStatus(''); }}
              >
                Clear filters
              </Button>
            )}
          />
        </Card>
      ) : (
        <>
          <Card className="py-1">
            <div className="divide-y divide-line">
              {rows.map((txn) => (
                <CreditTransactionRow
                  key={txn.credit_transaction_id}
                  transaction={txn}
                  onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
                />
              ))}
            </div>
          </Card>

          {error && (
            <p className="mt-3 text-center text-xs text-alert">{friendlyError(error)}</p>
          )}

          {hasNext && (
            <Button
              variant="outline"
              size="md"
              full
              className="mt-4"
              loading={loadingMore}
              onClick={() => load(page + 1, false)}
            >
              Load more
            </Button>
          )}
        </>
      )}
    </div>
  );
}

/* ── Detail and receipt ─────────────────────────────────────────────────── */

/* How long to keep asking about a processing payment before leaving it to the
   server's own poller. A UPI collect can take a couple of minutes; beyond that,
   polling from an open tab is just burning battery. */
const POLL_EVERY_MS = 4000;
const POLL_FOR_MS = 150000;

function heroFor(txn) {
  const debit = txn.direction === 'DEBIT';
  const isPayment = txn.type === 'PAYMENT';
  const who = txn.merchant_name || CREDIT_TYPE_LABEL[txn.type] || 'this transaction';

  switch (txn.status) {
    case 'SUCCEEDED':
      if (isPayment) {
        return {
          kind: 'success',
          title: 'Bill paid',
          subtitle: `${money(txn.amount)} of credit is available to spend again.`,
        };
      }
      if (txn.type === 'REFUND') {
        return { kind: 'success', title: 'Refund received', subtitle: `From ${who}.` };
      }
      return {
        kind: 'success',
        title: debit ? 'Payment successful' : 'Completed',
        subtitle: debit ? `Paid to ${who}.` : null,
      };
    case 'PROCESSING':
    case 'PENDING':
      return {
        kind: 'pending',
        title: 'Payment processing',
        subtitle: 'Waiting for your bank to confirm. Your credit is restored the moment it does - do not pay again.',
      };
    case 'CANCELLED':
      return {
        kind: 'cancelled',
        title: 'Payment cancelled',
        subtitle: 'Nothing was charged.',
      };
    case 'REVERSED':
      return {
        kind: 'cancelled',
        title: 'Refunded',
        subtitle: `${who} refunded this payment in full.`,
      };
    default:
      return {
        kind: 'failure',
        title: isPayment ? 'Payment failed' : 'Payment declined',
        subtitle: txn.failure_reason || 'The payment could not be completed. Nothing was charged.',
      };
  }
}

export function CreditTransactionDetail() {
  const { transactionId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = useReturnTo();
  const toast = useToast();

  // Arriving straight from a payment gets the animated result; opening an old
  // transaction from the list does not replay a celebration for it.
  const fresh = Boolean(location.state?.fresh);

  const [txn, setTxn] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await endpoints.credit.transaction(transactionId);
      setTxn(response.data);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => { load(); }, [load]);

  const processing = txn && (txn.status === 'PROCESSING' || txn.status === 'PENDING');
  const isBillPayment = txn?.type === 'PAYMENT';

  /* A processing bill payment is resolved by the server asking the gateway.
     This screen just keeps asking the server, in the background so no loader
     flashes over the page every few seconds. */
  useEffect(() => {
    if (!processing || !isBillPayment) return undefined;
    setPolling(true);
    const started = Date.now();
    let stopped = false;

    const timer = setInterval(async () => {
      if (Date.now() - started > POLL_FOR_MS) {
        clearInterval(timer);
        setPolling(false);
        return;
      }
      try {
        const response = await endpoints.credit.verifyBill(
          transactionId, {}, { background: true },
        );
        if (stopped) return;
        const next = response.data?.transaction;
        if (next && next.status !== 'PROCESSING') {
          setTxn(next);
          clearInterval(timer);
          setPolling(false);
          if (next.status === 'SUCCEEDED') toast.success('Payment confirmed. Your credit is restored.');
        }
      } catch {
        /* One failed check is not an answer. Keep asking. */
      }
    }, POLL_EVERY_MS);

    return () => {
      stopped = true;
      clearInterval(timer);
      setPolling(false);
    };
  }, [processing, isBillPayment, transactionId, toast]);

  async function checkNow() {
    setBusy(true);
    try {
      const response = await endpoints.credit.verifyBill(transactionId);
      setTxn(response.data.transaction);
    } catch (err) {
      toast.error(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelPayment() {
    setBusy(true);
    try {
      const response = await endpoints.credit.cancelBill(transactionId);
      setTxn(response.data.transaction);
      toast.info(response.message || 'Payment updated.');
    } catch (err) {
      toast.error(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Transaction" back="/credit/transactions" />
        <Card className="space-y-3 p-6">
          <Skeleton className="mx-auto h-20 w-20 rounded-full" />
          <Skeleton className="mx-auto h-8 w-40" />
          <Skeleton className="h-40 w-full" />
        </Card>
      </div>
    );
  }

  if (!txn) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Transaction" back="/credit/transactions" />
        <ErrorCard
          error={error}
          title={error?.status === 404 ? 'Transaction not found' : 'We could not load this transaction'}
          onRetry={error?.status === 404 ? undefined : load}
        />
      </div>
    );
  }

  const debit = txn.direction === 'DEBIT';
  const hero = heroFor(txn);
  const settled = txn.status === 'SUCCEEDED' || txn.status === 'REVERSED';
  const category = categoryLabel(txn.merchant_category);

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader
        title={fresh ? '' : 'Transaction'}
        back="/credit/transactions"
        action={!fresh && <TransactionStatusBadge transaction={txn} />}
      />

      <Card className="mb-4 overflow-hidden p-6 text-center sm:p-8">
        {txn.is_test && (
          <p className="mb-4 inline-flex rounded-full bg-amber-50 px-2.5 py-1 text-2xs font-semibold uppercase tracking-wider text-amber-700">
            Test transaction
          </p>
        )}
        <StatusHero
          kind={hero.kind}
          title={hero.title}
          subtitle={hero.subtitle}
          amount={`${settled ? (debit ? '−' : '+') : ''}${money(txn.amount)}`}
          amountTone={!settled ? 'text-slate' : debit ? 'text-ink' : 'text-mint-700'}
        />

        {processing && polling && (
          <p className="mt-4 inline-flex items-center gap-2 text-2xs text-slate">
            <Loader3D size="small" />
            Checking with your bank automatically…
          </p>
        )}
      </Card>

      <Card className="mb-4 divide-y divide-line py-1">
        <Row label="Transaction ID" value={txn.reference} mono />
        <Row label="Status" value={<TransactionStatusBadge transaction={txn} />} />
        <Row label="Type" value={CREDIT_TYPE_LABEL[txn.type] || txn.type} />
        {txn.merchant_name && <Row label="Merchant" value={txn.merchant_name} />}
        {category && <Row label="Category" value={category} />}
        {txn.credit_purpose && <Row label="Credit purpose" value={txn.credit_purpose} />}
        {txn.payment_method_label && <Row label="Paid using" value={txn.payment_method_label} />}
        <Row label="Date & time" value={dateTime(txn.created_on)} />
        {txn.settled_at && txn.settled_at !== txn.created_on && (
          <Row label="Settled" value={dateTime(txn.settled_at)} />
        )}
        <Row label="Amount" value={money(txn.amount)} mono />
        {Number(txn.refunded_amount) > 0 && (
          <Row label="Refunded" value={money(txn.refunded_amount)} mono tone="good" />
        )}
        {txn.available_after != null && (
          <Row
            label={settled ? 'Available credit after' : 'Available credit'}
            value={money(txn.available_after)}
            mono
          />
        )}
        {txn.balance_after != null && settled && (
          <Row label="Amount owed after" value={money(txn.balance_after)} mono />
        )}
        {txn.gateway_reference && <Row label="Bank reference" value={txn.gateway_reference} mono />}
        {txn.description && txn.type === 'PURCHASE' && <Row label="Note" value={txn.description} />}
        {txn.failure_reason && !settled && (
          <Row label="Reason" value={txn.failure_reason} tone="alert" />
        )}
      </Card>

      <div className="space-y-2">
        {processing && isBillPayment && (
          <>
            <Button variant="outline" size="lg" full loading={busy} onClick={checkNow}>
              Check status now
            </Button>
            <Button variant="ghost" size="lg" full disabled={busy} onClick={cancelPayment}>
              I did not pay - cancel this
            </Button>
          </>
        )}

        {txn.status === 'FAILED' && isBillPayment && (
          <Button variant="mint" size="lg" full onClick={() => navigate('/credit/pay', { replace: fresh })}>
            Try the payment again
          </Button>
        )}
        {txn.status === 'FAILED' && txn.type === 'PURCHASE' && txn.failure_code === 'INSUFFICIENT_CREDIT' && (
          <Button variant="mint" size="lg" full onClick={() => navigate('/credit/pay', { replace: fresh })}>
            Pay your bill to free up credit
          </Button>
        )}

        {txn.statement_id && (
          <Button
            variant="outline"
            size="lg"
            full
            onClick={() => navigate(`/credit/statements/${txn.statement_id}`)}
          >
            View the statement this was billed on
          </Button>
        )}

        {fresh ? (
          <Button
            variant={txn.status === 'SUCCEEDED' ? 'mint' : 'ghost'}
            size="lg"
            full
            onClick={() => returnTo('/credit')}
          >
            Done
          </Button>
        ) : (
          !txn.statement_id && settled && txn.status === 'SUCCEEDED' && (
            <p className="pt-2 text-center text-2xs text-slate">
              Not yet billed. This will appear on your next statement.
            </p>
          )
        )}
      </div>
    </div>
  );
}
