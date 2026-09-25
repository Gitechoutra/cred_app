import { cx } from '../ui';
import { date, money } from '../../utils/format';

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
 */

export const CREDIT_TYPE_LABEL = {
  PURCHASE: 'Purchase',
  PAYMENT: 'Bill payment',
  REFUND: 'Refund',
  FEE: 'Fee',
};

export function CreditTransactionRow({ transaction, onClick, showBalance = true }) {
  const debit = transaction.direction === 'DEBIT';
  const label = CREDIT_TYPE_LABEL[transaction.type] || transaction.type;

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-3 px-1 py-3.5 text-left transition hover:bg-mist/40 active:opacity-70"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">
          {transaction.merchant_name || label}
        </p>
        <p className="mt-0.5 truncate text-2xs text-slate">
          {label} · {date(transaction.created_on)}
          {transaction.is_test && ' · TEST'}
        </p>
      </div>

      <div className="shrink-0 text-right">
        <p
          className={cx(
            'money text-sm font-semibold',
            debit ? 'text-ink' : 'text-mint-700',
          )}
        >
          {debit ? '−' : '+'}{money(transaction.amount)}
        </p>
        {showBalance && transaction.balance_after != null && (
          <p className="money mt-0.5 text-2xs text-slate">
            bal {money(transaction.balance_after)}
          </p>
        )}
      </div>
    </button>
  );
}
