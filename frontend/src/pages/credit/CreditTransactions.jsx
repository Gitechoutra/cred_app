import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Row, Skeleton, Tabs, cx,
} from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Everything that has happened on the credit line.
 *
 * Debits and credits are told apart by sign and colour, not only by a type
 * label: a list where a purchase and a refund look identical except for one word
 * is a list people misread.
 *
 * `balance_after` is shown on each row because it is what the account said at
 * the time, which is the only useful answer to "why is my balance this?". It
 * comes from the stored column rather than a running total computed here - a sum
 * recomputed in the browser would paper over any drift instead of showing it.
 */

// `value`, not `id`: the shared Tabs component keys on tab.value, and an `id`
// would leave every tab comparing undefined against the active filter.
const FILTERS = [
  { value: '', label: 'All' },
  { value: 'PURCHASE', label: 'Spends' },
  { value: 'PAYMENT', label: 'Payments' },
  { value: 'REFUND', label: 'Refunds' },
  { value: 'FEE', label: 'Fees' },
];

const TYPE_LABEL = {
  PURCHASE: 'Purchase',
  PAYMENT: 'Bill payment',
  REFUND: 'Refund',
  FEE: 'Fee',
};

export function CreditTransactionList() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');

  const { data, loading } = useFetch(
    () => endpoints.credit.transactions(1, filter), [filter],
  );

  const transactions = data || [];

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader title="Card activity" back="/credit" />

      <Tabs
        tabs={FILTERS}
        active={filter}
        onChange={setFilter}
        className="mb-4"
      />

      {loading ? (
        <Card><Skeleton className="h-64 w-full" /></Card>
      ) : transactions.length === 0 ? (
        <EmptyState
          title={filter ? 'Nothing of this kind yet' : 'No activity yet'}
          description={
            filter
              ? 'Try another filter.'
              : 'Purchases and payments on this card will appear here.'
          }
        />
      ) : (
        <Card className="py-1">
          <div className="divide-y divide-line">
            {transactions.map((txn) => {
              const debit = txn.direction === 'DEBIT';
              return (
                <button
                  key={txn.credit_transaction_id}
                  type="button"
                  onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
                  className="flex w-full items-center justify-between gap-3 py-3.5 text-left transition hover:bg-mist/40"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">
                      {txn.merchant_name || TYPE_LABEL[txn.type] || txn.type}
                    </p>
                    <p className="mt-0.5 text-2xs text-slate">
                      {TYPE_LABEL[txn.type] || txn.type} · {date(txn.created_on)}
                      {txn.is_test && ' · TEST'}
                    </p>
                  </div>

                  <div className="shrink-0 text-right">
                    <p
                      className={cx(
                        'money text-sm font-semibold',
                        debit ? 'text-ink' : 'text-mint-700',
                      )}
                    >
                      {debit ? '−' : '+'}{money(txn.amount)}
                    </p>
                    {txn.balance_after != null && (
                      <p className="money mt-0.5 text-2xs text-slate">
                        bal {money(txn.balance_after)}
                      </p>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

export function CreditTransactionDetail() {
  const { transactionId } = useParams();
  const navigate = useNavigate();

  const { data: txn, loading } = useFetch(
    () => endpoints.credit.transaction(transactionId), [transactionId],
  );

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Transaction" back />
        <Card><Skeleton className="h-56 w-full" /></Card>
      </div>
    );
  }

  if (!txn) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Transaction" back />
        <Card className="text-center">
          <p className="text-sm text-slate">We could not find that transaction.</p>
        </Card>
      </div>
    );
  }

  const debit = txn.direction === 'DEBIT';

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader title="Transaction" back />

      <Card className="mb-4 text-center">
        {txn.is_test && (
          <Badge tone="warn" dot>Test transaction</Badge>
        )}
        <p
          className={cx(
            'money mt-2 text-4xl font-bold',
            debit ? 'text-ink' : 'text-mint-700',
          )}
        >
          {debit ? '−' : '+'}{money(txn.amount)}
        </p>
        <p className="mt-1 text-sm text-slate">
          {txn.merchant_name || TYPE_LABEL[txn.type] || txn.type}
        </p>
        <div className="mt-3">
          <Badge tone={txn.status === 'SUCCEEDED' ? 'good' : 'warn'} dot>
            {txn.status}
          </Badge>
        </div>
      </Card>

      <Card>
        <Row label="Type" value={TYPE_LABEL[txn.type] || txn.type} />
        {txn.merchant_category && (
          <Row
            label="Category"
            value={txn.merchant_category.replace(/_/g, ' ').toLowerCase()}
          />
        )}
        {txn.description && <Row label="Note" value={txn.description} />}
        {txn.balance_after != null && (
          <Row
            label="Balance after this"
            value={money(txn.balance_after)}
            mono
          />
        )}
        <Row label="When" value={date(txn.created_on)} />
        {txn.settled_at && <Row label="Settled" value={date(txn.settled_at)} />}
        <Row
          label="Reference"
          value={txn.credit_transaction_id.slice(0, 13).toUpperCase()}
          mono
        />
      </Card>

      {txn.statement_id && (
        <Button
          variant="outline"
          size="lg"
          full
          className="mt-4"
          onClick={() => navigate(`/credit/statements/${txn.statement_id}`)}
        >
          View the statement this was billed on
        </Button>
      )}

      {!txn.statement_id && txn.status === 'SUCCEEDED' && (
        <p className="mt-4 text-center text-2xs text-slate">
          Not yet billed. This will appear on your next statement.
        </p>
      )}
    </div>
  );
}
