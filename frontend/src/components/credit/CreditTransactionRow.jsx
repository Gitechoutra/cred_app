import { cx } from '../ui';
import { dateTime, money } from '../../utils/format';
import {
  CREDIT_TYPE_LABEL, TransactionStatusBadge, categoryLabel, transactionStatus,
} from './CreditUI';

/**
 * One movement on a credit line.
 *
 * Its own component rather than the shared TransactionRow, which is built for
 * ledger rows and decides credit-versus-debit with
 * `type === 'REVERSAL_REFUND'`. A credit-line PAYMENT would fall on the wrong
 * side of that test and render as −₹5,000 on the home screen while the activity
 * list showed +₹5,000 for the same payment. The direction is not something to
 * re-derive per screen from a type name: the server already sends it, so this
 * reads it.
 *
 * A row that did not move money - declined, cancelled, still processing - is
 * struck through and badged rather than shown like a settled one, so a
 * declined ₹30,000 is never mistaken for a spend.
 */

export { CREDIT_TYPE_LABEL };

export function CreditTransactionRow({ transaction, onClick, showBalance = true }) {
  const debit = transaction.direction === 'DEBIT';
  const label = CREDIT_TYPE_LABEL[transaction.type] || transaction.type;
  const settled = transaction.status === 'SUCCEEDED' || transaction.status === 'REVERSED';
  const { tone } = transactionStatus(transaction);
  const category = categoryLabel(transaction.merchant_category);

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-3 rounded-xl px-1 py-3.5 text-left transition hover:bg-mist/50 active:opacity-70"
    >
      <span
        aria-hidden="true"
        className={cx(
          'grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-bold',
          !settled && tone === 'alert' && 'bg-red-50 text-alert',
          !settled && tone !== 'alert' && 'bg-amber-50 text-warn',
          settled && debit && 'bg-mist text-ink',
          settled && !debit && 'bg-mint-50 text-mint-800',
        )}
      >
        {(transaction.merchant_name || label).charAt(0).toUpperCase()}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">
          {transaction.merchant_name || label}
        </p>
        <p className="mt-0.5 truncate text-2xs text-slate">
          {category || label} · {dateTime(transaction.created_on)}
          {transaction.is_test && ' · TEST'}
        </p>
        {transaction.status !== 'SUCCEEDED' && (
          <TransactionStatusBadge transaction={transaction} className="mt-1.5" />
        )}
      </div>

      <div className="shrink-0 text-right">
        <p
          className={cx(
            'money text-sm font-semibold',
            !settled && 'text-slate-light line-through',
            settled && (debit ? 'text-ink' : 'text-mint-700'),
          )}
        >
          {debit ? '−' : '+'}{money(transaction.amount)}
        </p>
        {showBalance && transaction.available_after != null && settled && (
          <p className="money mt-0.5 text-2xs text-slate">
            {money(transaction.available_after, { decimals: 0 })} avail.
          </p>
        )}
      </div>
    </button>
  );
}
