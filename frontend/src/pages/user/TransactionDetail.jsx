import { useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Card, EmptyState, Row, Skeleton, cx } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import {
  dateTime, money, statusLabel, statusTone, transactionLabel,
} from '../../utils/format';

export default function TransactionDetail() {
  const { transactionId } = useParams();
  const { data: transaction, loading } = useFetch(
    () => endpoints.transactions.get(transactionId),
    [transactionId],
  );

  if (loading) {
    return (
      <div className="">
        <PageHeader title="Transaction" back="/transactions" />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-56 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!transaction) {
    return (
      <div className="">
        <PageHeader title="Transaction" back="/transactions" />
        <EmptyState title="Transaction not found" />
      </div>
    );
  }

  const tone = statusTone(transaction.status);

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Receipt" back="/transactions" />

        <div className="space-y-4 px-4 pt-4">
          <section className="rounded-2xl border border-line bg-canvas p-5 text-center">
            <p className="text-xs text-slate">{transactionLabel(transaction.type)}</p>
            <p className="money mt-2 text-[2rem] font-bold leading-none text-ink">
              {money(transaction.gross_amount)}
            </p>
            <div className="mt-3 flex justify-center">
              <Badge tone={tone} dot>{statusLabel(transaction.status)}</Badge>
            </div>
          </section>

          <Card className="divide-y divide-line py-1">
            <Row label="From" value={transaction.source} mono />
            <Row label="To" value={transaction.destination} mono />
            <Row label="Amount" value={money(transaction.net_amount)} mono />
            {Number(transaction.fee_amount) > 0 && (
              <Row label="Convenience fee" value={money(transaction.fee_amount)} mono />
            )}
            {Number(transaction.tax_amount) > 0 && (
              <Row label="GST" value={money(transaction.tax_amount)} mono />
            )}
            <Row label="Total" value={money(transaction.gross_amount)} mono />
            {transaction.source_opening_balance != null && (
              <Row label="Card balance before" value={money(transaction.source_opening_balance)} mono />
            )}
            {transaction.source_closing_balance != null && (
              <Row label="Card balance after" value={money(transaction.source_closing_balance)} mono />
            )}
            {transaction.destination_opening_balance != null && (
              <Row label="Account balance before" value={money(transaction.destination_opening_balance)} mono />
            )}
            {transaction.destination_closing_balance != null && (
              <Row label="Account balance after" value={money(transaction.destination_closing_balance)} mono />
            )}
            {transaction.utr && <Row label="UTR" value={transaction.utr} mono />}
            {transaction.gateway_reference && (
              <Row label="Gateway reference" value={transaction.gateway_reference} mono />
            )}
            <Row label="Date" value={dateTime(transaction.created_on)} />
          </Card>

          {transaction.failure_reason && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3.5">
              <p className="text-xs font-semibold text-alert">Why this failed</p>
              <p className="mt-1 text-xs leading-relaxed text-alert/85">
                {transaction.failure_reason}
              </p>
            </div>
          )}

          {/* The double-entry journal behind this transaction (PRD FR-010).
              Surfaced to the user, not hidden in an admin console - it is their
              money, and an immutable record is only reassuring if visible. */}
          {transaction.ledger_entries?.length > 0 && (
            <Card className="py-1">
              <p className="px-1 py-2 text-2xs font-semibold uppercase tracking-wider text-slate">
                Accounting record
              </p>

              <div className="divide-y divide-line">
                {transaction.ledger_entries.map((entry, index) => (
                  <div key={index} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-ink">
                        {entry.account_code.replace(/_/g, ' ')}
                      </p>
                      {entry.narration && (
                        <p className="truncate text-2xs text-slate">{entry.narration}</p>
                      )}
                    </div>

                    <span
                      className={cx(
                        'money shrink-0 text-xs font-medium',
                        Number(entry.debit) > 0 ? 'text-ink' : 'text-mint-700',
                      )}
                    >
                      {Number(entry.debit) > 0
                        ? `Dr ${money(entry.debit)}`
                        : `Cr ${money(entry.credit)}`}
                    </span>
                  </div>
                ))}
              </div>

              <p className="px-1 pb-2 pt-1 text-2xs leading-relaxed text-slate">
                This record is immutable. Corrections are posted as new entries,
                never by editing history.
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
