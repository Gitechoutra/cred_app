import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Row, Skeleton, cx,
} from '../../components/ui';
import { CreditTransactionRow } from '../../components/credit/CreditTransactionRow';
import { ErrorCard } from '../../components/credit/CreditUI';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Monthly statements.
 *
 * Every figure here is the one that was issued, read back from the statement
 * row rather than recomputed from the transaction list. That distinction is the
 * whole point of storing them: a payment that lands a second after the cycle was
 * cut must not change what a statement said, and a statement that quietly
 * restates itself is not a bill, it is an estimate. The available credit shown
 * is the figure at the close of the cycle, for the same reason.
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

const STATUS_LABEL = {
  PAID: 'Paid',
  PARTIALLY_PAID: 'Partly paid',
  UNPAID: 'Unpaid',
  OVERDUE: 'Overdue',
};

export function CreditStatementList() {
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useFetch(() => endpoints.credit.statements(1), []);

  const statements = data || [];

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader title="Statements" subtitle="One for each billing cycle." back="/credit" />

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 w-full rounded-2xl" />)}
        </div>
      ) : error ? (
        <ErrorCard error={error} title="We could not load your statements" onRetry={refetch} />
      ) : statements.length === 0 ? (
        <Card>
          <EmptyState
            title="No statements yet"
            description="Your first statement is generated at the end of your billing cycle. Everything you spend until then is listed under Transactions."
            action={
              <Button variant="outline" size="sm" onClick={() => navigate('/credit/transactions')}>
                View transactions
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {statements.map((statement, index) => (
            <Card
              key={statement.statement_id}
              onClick={() => navigate(`/credit/statements/${statement.statement_id}`)}
              style={{ animationDelay: `${index * 40}ms` }}
              className="stagger p-4 sm:p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink">
                    {date(statement.period_start)} – {date(statement.period_end)}
                  </p>
                  <p className="mt-0.5 truncate text-2xs text-slate">{statement.statement_number}</p>
                </div>
                <Badge tone={TONE[statement.status] || 'neutral'} dot>
                  {STATUS_LABEL[statement.status] || statement.status}
                </Badge>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-line pt-3">
                <div className="min-w-0">
                  <p className="text-2xs uppercase tracking-wider text-slate">Total due</p>
                  <p className="money mt-0.5 truncate text-sm font-bold text-ink">
                    {money(statement.total_amount_due)}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="text-2xs uppercase tracking-wider text-slate">Minimum</p>
                  <p className="money mt-0.5 truncate text-sm font-semibold text-ink">
                    {money(statement.minimum_due)}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="text-2xs uppercase tracking-wider text-slate">Due date</p>
                  <p className="mt-0.5 truncate text-sm font-semibold text-ink">
                    {date(statement.due_date, { withYear: false })}
                  </p>
                </div>
              </div>
              {statement.amount_outstanding > 0 && statement.status !== 'PAID' && (
                <p className="money mt-2 text-2xs text-slate">
                  {money(statement.amount_outstanding)} still to pay
                </p>
              )}
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

  const { data: statement, loading, error, refetch } = useFetch(
    () => endpoints.credit.statement(statementId), [statementId],
  );

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Statement" back="/credit/statements" />
        <Skeleton className="h-44 w-full rounded-2xl" />
        <Skeleton className="mt-4 h-72 w-full rounded-2xl" />
      </div>
    );
  }

  if (!statement) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="Statement" back="/credit/statements" />
        <ErrorCard
          error={error}
          title={error?.status === 404 ? 'Statement not found' : 'We could not load this statement'}
          onRetry={error?.status === 404 ? undefined : refetch}
        />
      </div>
    );
  }

  const owing = statement.amount_outstanding > 0 && statement.status !== 'PAID';
  const transactions = statement.transactions || [];

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="Statement"
        subtitle={`${date(statement.period_start)} – ${date(statement.period_end)}`}
        back="/credit/statements"
        action={
          <Badge tone={TONE[statement.status] || 'neutral'} dot>
            {STATUS_LABEL[statement.status] || statement.status}
          </Badge>
        }
      />

      <Card className="mb-4 overflow-hidden !p-0">
        <div className="bg-gradient-to-br from-ink via-[#0f1a1f] to-[#062019] px-5 py-6 text-center text-white sm:py-8">
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-white/60">
            {owing ? 'Amount due' : 'Total billed'}
          </p>
          <p className="money mt-1 text-4xl font-bold tracking-tight">
            {money(owing ? statement.amount_outstanding : statement.total_amount_due)}
          </p>
          <p className="mt-2 text-sm text-white/70">
            {owing
              ? `Due by ${date(statement.due_date)}`
              : statement.amount_paid > 0 ? 'Paid in full - thank you' : 'Nothing was owed this cycle'}
          </p>
        </div>

        <div className="grid grid-cols-2 divide-x divide-line text-center sm:grid-cols-4">
          {[
            { label: 'Total due', value: money(statement.total_amount_due) },
            { label: 'Minimum due', value: money(statement.minimum_due) },
            { label: 'Due date', value: date(statement.due_date) },
            { label: 'Available credit', value: statement.available_credit != null ? money(statement.available_credit) : '—' },
          ].map((item, index) => (
            <div key={item.label} className={cx('min-w-0 p-3', index >= 2 && 'border-t border-line sm:border-t-0')}>
              <p className="truncate text-2xs uppercase tracking-wider text-slate">{item.label}</p>
              <p className="money mt-0.5 truncate text-sm font-semibold text-ink">{item.value}</p>
            </div>
          ))}
        </div>

        {owing && (
          <div className="border-t border-line p-4">
            <Button variant="mint" size="lg" full onClick={() => navigate('/credit/pay')}>
              Pay this bill
            </Button>
            {statement.minimum_outstanding > 0 && (
              <p className="mt-2 text-center text-2xs text-slate">
                Pay at least{' '}
                <span className="money font-semibold text-ink">{money(statement.minimum_outstanding)}</span>
                {' '}by {date(statement.due_date)} to avoid a late fee.
              </p>
            )}
          </div>
        )}
      </Card>

      <Card className="mb-4 p-5 sm:p-6">
        <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate">Summary</p>
        <Row label="Opening balance" value={money(statement.opening_balance)} mono />
        <Row label="Purchases" value={`+ ${money(statement.total_purchases)}`} mono />
        {statement.total_fees > 0 && (
          <Row label="Fees" value={`+ ${money(statement.total_fees)}`} mono tone="alert" />
        )}
        <Row label="Payments" value={`− ${money(statement.total_payments)}`} mono />
        <Row label="Refunds" value={`− ${money(statement.total_refunds)}`} mono />

        <div className="mt-2 flex items-baseline justify-between gap-4 border-t border-line pt-3">
          <span className="text-sm font-semibold text-ink">Closing balance</span>
          <span className="money text-base font-bold text-ink">{money(statement.closing_balance)}</span>
        </div>

        <Row label="Total amount due" value={money(statement.total_amount_due)} mono className="mt-1" />
        <Row
          label={`Minimum amount due (${statement.minimum_due_percent}%)`}
          value={money(statement.minimum_due)}
          mono
        />
        <Row label="Due date" value={date(statement.due_date)} />
        {statement.amount_paid > 0 && (
          <Row label="Paid since statement" value={money(statement.amount_paid)} mono tone="good" />
        )}
        {statement.credit_limit != null && (
          <Row label="Credit limit" value={money(statement.credit_limit)} mono />
        )}
        {statement.available_credit != null && (
          <Row label="Available credit at statement date" value={money(statement.available_credit)} mono />
        )}
        <Row label="Statement number" value={statement.statement_number} mono />
      </Card>

      {statement.late_fee_charged && (
        <Card className="mb-4 border-red-200 bg-red-50/50">
          <p className="text-sm font-medium text-alert">A late payment fee was charged on this statement</p>
          <p className="mt-1 text-2xs leading-relaxed text-slate">
            Paying at least the minimum due before the due date avoids it.
          </p>
        </Card>
      )}

      <Card className="py-1">
        <p className="px-1 py-2.5 text-2xs font-semibold uppercase tracking-wider text-slate">
          {transactions.length} transaction{transactions.length === 1 ? '' : 's'} this cycle
        </p>
        {transactions.length === 0 ? (
          <p className="px-1 pb-3 text-sm text-slate">Nothing was billed in this cycle.</p>
        ) : (
          <div className="divide-y divide-line">
            {transactions.map((txn) => (
              <CreditTransactionRow
                key={txn.credit_transaction_id}
                transaction={txn}
                showBalance={false}
                onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
