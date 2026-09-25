import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Row, Skeleton, cx,
} from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Monthly statements.
 *
 * Every figure here is the one that was issued, read back from the statement
 * row rather than recomputed from the transaction list. That distinction is the
 * whole point of storing them: a spend that lands a second after the cycle was
 * cut must not change what a statement said, and a statement that quietly
 * restates itself is not a bill, it is an estimate.
 *
 * The arithmetic is shown in full - opening, purchases, fees, payments, refunds,
 * closing - so a disputed number can be traced without asking support.
 */

const TONE = {
  PAID: 'good',
  PARTIALLY_PAID: 'warn',
  UNPAID: 'warn',
  OVERDUE: 'alert',
};

export function CreditStatementList() {
  const navigate = useNavigate();
  const { data, loading } = useFetch(() => endpoints.credit.statements(1), []);

  const statements = data || [];

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Statements"
        subtitle="One for each billing cycle."
        back="/credit"
      />

      {loading ? (
        <Card><Skeleton className="h-56 w-full" /></Card>
      ) : statements.length === 0 ? (
        <EmptyState
          title="No statements yet"
          description="Your first one arrives at the end of this billing cycle."
        />
      ) : (
        <div className="space-y-3">
          {statements.map((statement, index) => (
            <Card
              key={statement.statement_id}
              onClick={() => navigate(`/credit/statements/${statement.statement_id}`)}
              style={{ animationDelay: `${index * 40}ms` }}
              className="stagger cursor-pointer transition hover:border-ink/20"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink">
                    {date(statement.period_start)} – {date(statement.period_end)}
                  </p>
                  <p className="mt-0.5 text-2xs text-slate">
                    {statement.statement_number}
                  </p>
                  <p className="mt-2 text-xs text-slate">
                    Due {date(statement.due_date)}
                  </p>
                </div>

                <div className="shrink-0 text-right">
                  <p className="money text-xl font-bold text-ink">
                    {money(statement.closing_balance)}
                  </p>
                  {statement.amount_outstanding > 0 && (
                    <p className="money mt-0.5 text-2xs text-slate">
                      {money(statement.amount_outstanding)} still owed
                    </p>
                  )}
                  <div className="mt-2 flex justify-end">
                    <Badge tone={TONE[statement.status] || 'neutral'} dot>
                      {statement.status.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export function CreditStatementDetail() {
  const { statementId } = useParams();
  const navigate = useNavigate();

  const { data: statement, loading } = useFetch(
    () => endpoints.credit.statement(statementId), [statementId],
  );

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Statement" back />
        <Card><Skeleton className="h-72 w-full" /></Card>
      </div>
    );
  }

  if (!statement) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Statement" back />
        <Card className="text-center">
          <p className="text-sm text-slate">We could not find that statement.</p>
        </Card>
      </div>
    );
  }

  const owing = statement.amount_outstanding > 0;
  const transactions = statement.transactions || [];

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Statement"
        subtitle={`${date(statement.period_start)} – ${date(statement.period_end)}`}
        back
        action={
          <Badge tone={TONE[statement.status] || 'neutral'} dot>
            {statement.status.replace(/_/g, ' ')}
          </Badge>
        }
      />

      <Card className="mb-4 text-center">
        <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
          {owing ? 'Amount due' : 'Total billed'}
        </p>
        <p className="money mt-1 text-4xl font-bold text-ink">
          {money(owing ? statement.amount_outstanding : statement.closing_balance)}
        </p>
        <p className="mt-2 text-sm text-slate">
          {owing
            ? `By ${date(statement.due_date)}`
            : `Settled in full${statement.amount_paid > 0 ? '' : ' - nothing was owed'}`}
        </p>

        {owing && statement.minimum_outstanding > 0 && (
          <p className="mt-3 text-xs text-slate">
            Minimum to stay current{' '}
            <span className="money font-medium text-ink">
              {money(statement.minimum_outstanding)}
            </span>
          </p>
        )}

        {owing && (
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-5"
            onClick={() => navigate('/credit/pay')}
          >
            Pay this bill
          </Button>
        )}
      </Card>

      <Card className="mb-4">
        <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate">
          How this was calculated
        </p>
        <Row label="Opening balance" value={money(statement.opening_balance)} mono />
        <Row label="Purchases" value={`+ ${money(statement.total_purchases)}`} mono />
        {statement.total_fees > 0 && (
          <Row label="Fees" value={`+ ${money(statement.total_fees)}`} mono tone="alert" />
        )}
        {statement.total_payments > 0 && (
          <Row label="Payments" value={`− ${money(statement.total_payments)}`} mono />
        )}
        {statement.total_refunds > 0 && (
          <Row label="Refunds" value={`− ${money(statement.total_refunds)}`} mono />
        )}

        <div className="mt-2 flex items-baseline justify-between gap-4 border-t border-line pt-3">
          <span className="text-sm font-medium text-ink">Closing balance</span>
          <span className="money text-base font-bold text-ink">
            {money(statement.closing_balance)}
          </span>
        </div>

        <Row
          label={`Minimum due (${statement.minimum_due_percent}%)`}
          value={money(statement.minimum_due)}
          mono
          className="mt-2"
        />
        {statement.amount_paid > 0 && (
          <Row label="Paid so far" value={money(statement.amount_paid)} mono />
        )}
      </Card>

      {statement.late_fee_charged && (
        <Card className="mb-4 border-alert/30 bg-red-50/50">
          <p className="text-sm font-medium text-alert">
            A late payment fee was charged on this statement
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-slate">
            It appears in the fees line above. Paying at least the minimum due
            before the due date avoids this.
          </p>
        </Card>
      )}

      <Card className="py-1">
        <p className="px-1 py-2.5 text-2xs font-semibold uppercase tracking-wider text-slate">
          {transactions.length} transaction{transactions.length === 1 ? '' : 's'}
        </p>
        {transactions.length === 0 ? (
          <p className="px-1 pb-3 text-sm text-slate">
            Nothing was billed in this cycle.
          </p>
        ) : (
          <div className="divide-y divide-line">
            {transactions.map((txn) => {
              const debit = txn.direction === 'DEBIT';
              return (
                <button
                  key={txn.credit_transaction_id}
                  type="button"
                  onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
                  className="flex w-full items-center justify-between gap-3 py-3 text-left transition hover:bg-mist/40"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">
                      {txn.merchant_name || txn.description || txn.type}
                    </p>
                    <p className="mt-0.5 text-2xs text-slate">
                      {date(txn.created_on)}
                    </p>
                  </div>
                  <span
                    className={cx(
                      'money shrink-0 text-sm font-medium',
                      debit ? 'text-ink' : 'text-mint-700',
                    )}
                  >
                    {debit ? '−' : '+'}{money(txn.amount)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
