"""
portal/helpers/ledger_engine.py
===============================
The only writer of master_transactions and double_entry_ledger.

PRD FR-010 requires an immutable, audit-compliant record of every monetary
movement with zero-discrepancy reconciliation. That guarantee is only as strong
as the discipline around it, so every money path in CashU funnels through
post() here. Nothing else touches those two tables.

Why this is centralized
-----------------------
The PRD specifies PostgreSQL with serializable isolation. We are on MySQL
(version1.md deviation D1), so the balancing guarantee has to come from
application structure instead of the strongest database isolation level:

  - post() writes the transaction and its balanced entries in one atomic unit
  - every posting is validated to balance BEFORE it is flushed
  - account codes are checked against the seeded chart of accounts
  - status transitions are the only permitted mutation
  - self_audit() re-verifies the whole ledger nightly and screams on drift

Accounting model
----------------
CashU holds no customer funds (PRD: pure technology layer partnering with a
licensed PA). The ledger therefore records the platform's own position: what it
is owed by the gateway, what it owes users mid-flight, and what it earns.
"""

from contextlib import contextmanager
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from portal import db
from portal.models.base import utcnow
from portal.models.double_entry_ledger import DoubleEntryLedger
from portal.models.ledger_accounts import LedgerAccounts
from portal.models.master_transactions import (
    MasterTransactions, TransactionStatus,
)


class LedgerError(Exception):
    """Raised when a posting would violate an accounting invariant."""


class DuplicateTransaction(Exception):
    """
    Raised when idempotency_key already exists.

    Carries the original transaction so the caller can answer the retry with
    the first result instead of charging the card again (ERR-007, AC-004).
    """

    def __init__(self, transaction):
        super().__init__(f'Transaction already exists: {transaction.transaction_id}')
        self.transaction = transaction


# ── Chart of accounts ──────────────────────────────────────────────────────
# Codes referenced by the posting templates below. Seeded by seed_ledger_accounts.

class Account:
    GATEWAY_RECEIVABLE = 'GATEWAY_RECEIVABLE'   # asset: charged, not yet settled
    PAYOUT_CLEARING = 'PAYOUT_CLEARING'         # asset: with the payout partner
    USER_PAYABLE = 'USER_PAYABLE'               # liability: owed to the user
    BILLER_PAYABLE = 'BILLER_PAYABLE'           # liability: owed to an NBFC biller
    FEE_INCOME = 'FEE_INCOME'                   # income: convenience fee
    GST_PAYABLE = 'GST_PAYABLE'                 # liability: GST owed to the state
    GATEWAY_CHARGES = 'GATEWAY_CHARGES'         # expense: MDR paid to the PA
    REVERSAL_CLEARING = 'REVERSAL_CLEARING'     # asset: refund in flight
    SUSPENSE = 'SUSPENSE'                       # asset: unmatched, needs a human


def money(value) -> Decimal:
    """Quantize to the 2dp the columns actually store."""
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@contextmanager
def atomic():
    """
    Wrap a money operation in one commit-or-rollback unit.

    MySQL's default REPEATABLE READ plus row locks taken by SELECT ... FOR
    UPDATE inside this block is what stands in for the PRD's serializable
    PostgreSQL. Anything reading a balance to decide on a write must take that
    lock, or two concurrent requests can both pass the same limit check.
    """
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _validate_entries(entries):
    """
    Every posting must balance and name real accounts.

    Checked before the flush so an unbalanced posting is rejected outright
    rather than landing in the ledger and surfacing as a reconciliation
    discrepancy hours later.
    """
    if not entries or len(entries) < 2:
        raise LedgerError('A ledger posting requires at least two entries.')

    total_debit = sum(money(e.get('debit', 0)) for e in entries)
    total_credit = sum(money(e.get('credit', 0)) for e in entries)

    if total_debit != total_credit:
        raise LedgerError(
            f'Unbalanced posting: debits {total_debit} != credits {total_credit}'
        )
    if total_debit == 0:
        raise LedgerError('A ledger posting cannot be for zero.')

    for entry in entries:
        debit = money(entry.get('debit', 0))
        credit = money(entry.get('credit', 0))
        if debit and credit:
            raise LedgerError(
                f"Entry on {entry.get('account')} has both a debit and a credit; "
                'split it into two entries.'
            )
        if not debit and not credit:
            raise LedgerError(f"Entry on {entry.get('account')} is zero on both sides.")

    codes = {e['account'] for e in entries}
    known = {
        row.account_code
        for row in LedgerAccounts.query.filter(
            LedgerAccounts.account_code.in_(codes)
        ).all()
    }
    unknown = codes - known
    if unknown:
        raise LedgerError(f"Unknown ledger account code(s): {', '.join(sorted(unknown))}")


def post(
    *,
    user_id: str,
    transaction_type: str,
    gross_amount,
    net_amount,
    fee_amount=0,
    tax_amount=0,
    source_type: str,
    source_masked_ref: str,
    dest_type: str,
    dest_masked_ref: str,
    gateway_provider: str,
    idempotency_key: str,
    entries: list,
    status: str = TransactionStatus.INITIATED,
    gateway_ref_no: str = None,
    bank_rrn_utr: str = None,
    reverses_transaction_id: str = None,
    commit: bool = True,
) -> MasterTransactions:
    """
    Record a monetary movement and its balanced journal entries.

    `entries` is a list of dicts: {account, debit|credit, narration}.

    Raises DuplicateTransaction when idempotency_key is already used - the
    UNIQUE index is the duplicate-charge defence, and hitting it is a normal,
    expected outcome of a double-tapped button, not an error condition.
    """
    _validate_entries(entries)

    # Fast path: an obvious replay need not wait for the constraint to fire.
    existing = MasterTransactions.query.filter_by(
        idempotency_key=idempotency_key
    ).first()
    if existing:
        raise DuplicateTransaction(existing)

    txn = MasterTransactions(
        user_id=user_id,
        transaction_type=transaction_type,
        gross_amount=money(gross_amount),
        net_amount=money(net_amount),
        fee_amount=money(fee_amount),
        tax_amount=money(tax_amount),
        source_type=source_type,
        source_masked_ref=source_masked_ref,
        dest_type=dest_type,
        dest_masked_ref=dest_masked_ref,
        gateway_provider=gateway_provider,
        gateway_ref_no=gateway_ref_no,
        bank_rrn_utr=bank_rrn_utr,
        idempotency_key=idempotency_key,
        status=status,
        reverses_transaction_id=reverses_transaction_id,
    )
    db.session.add(txn)
    db.session.flush()   # assigns transaction_id without committing

    for entry in entries:
        db.session.add(
            DoubleEntryLedger(
                transaction_id=txn.transaction_id,
                account_code=entry['account'],
                debit_amount=money(entry.get('debit', 0)),
                credit_amount=money(entry.get('credit', 0)),
                narration=entry.get('narration'),
            )
        )

    if commit:
        try:
            db.session.commit()
        except IntegrityError:
            # Lost the race to a concurrent request carrying the same key.
            db.session.rollback()
            duplicate = MasterTransactions.query.filter_by(
                idempotency_key=idempotency_key
            ).first()
            if duplicate:
                raise DuplicateTransaction(duplicate)
            raise

    return txn


def post_entries(transaction, entries: list, *, commit: bool = True):
    """
    Attach a further balanced journal posting to an existing transaction.

    A transfer moves money twice - the card is charged, then the bank is paid -
    and both legs belong in the ledger. They do not both belong in the
    transaction list: one transfer is one thing that happened to the user, and
    posting the payout as its own MasterTransactions row made every transfer
    appear twice in their history, once at the principal and once at the total
    charged. The summary then added both together.

    So the second leg posts its entries here, against the transaction the
    charge already created. The ledger keeps all four entries and still
    balances; the user sees one payment.

    Idempotent by construction: if this transaction already carries an entry
    for the same account with the same amount, the posting has been made and
    the call is a no-op. Payout confirmation can arrive from the webhook and
    the poller at once.
    """
    _validate_entries(entries)

    existing = DoubleEntryLedger.query.filter_by(
        transaction_id=transaction.transaction_id
    ).all()

    def already_posted(entry):
        debit = money(entry.get('debit', 0))
        credit = money(entry.get('credit', 0))
        return any(
            row.account_code == entry['account']
            and money(row.debit_amount) == debit
            and money(row.credit_amount) == credit
            for row in existing
        )

    if all(already_posted(entry) for entry in entries):
        return transaction

    for entry in entries:
        db.session.add(DoubleEntryLedger(
            transaction_id=transaction.transaction_id,
            account_code=entry['account'],
            debit_amount=money(entry.get('debit', 0)),
            credit_amount=money(entry.get('credit', 0)),
            narration=entry.get('narration'),
        ))

    if commit:
        db.session.commit()

    return transaction


def transition(
    txn: MasterTransactions,
    new_status: str,
    *,
    failure_code: str = None,
    failure_reason: str = None,
    gateway_ref_no: str = None,
    bank_rrn_utr: str = None,
    commit: bool = True,
) -> MasterTransactions:
    """
    Move a transaction's status.

    The only mutation permitted on an append-only row. A transaction already in
    a terminal state is never moved again - a webhook that arrives late, twice,
    or out of order must not resurrect a settled transfer.
    """
    if txn.status in TransactionStatus.TERMINAL and new_status != txn.status:
        raise LedgerError(
            f'Transaction {txn.transaction_id} is terminal ({txn.status}); '
            f'refusing to move it to {new_status}.'
        )

    txn.status = new_status
    if failure_code:
        txn.failure_code = failure_code
    if failure_reason:
        txn.failure_reason = str(failure_reason)[:500]
    if gateway_ref_no:
        txn.gateway_ref_no = gateway_ref_no
    if bank_rrn_utr:
        txn.bank_rrn_utr = bank_rrn_utr

    if commit:
        db.session.commit()
    return txn


def reverse(
    original: MasterTransactions,
    *,
    reason: str,
    idempotency_key: str,
    commit: bool = True,
) -> MasterTransactions:
    """
    Post a compensating transaction (PRD FR-010).

    Financial rows are never edited or deleted, so a refund is a new
    transaction whose entries are the mirror image of the original. The history
    then shows both what happened and what corrected it.
    """
    original_entries = original.ledger_entries.all()
    if not original_entries:
        raise LedgerError(
            f'Transaction {original.transaction_id} has no ledger entries to reverse.'
        )

    mirrored = [
        {
            'account': entry.account_code,
            'debit': entry.credit_amount,
            'credit': entry.debit_amount,
            'narration': f'Reversal: {reason}',
        }
        for entry in original_entries
    ]

    reversal = post(
        user_id=original.user_id,
        transaction_type='REVERSAL_REFUND',
        gross_amount=original.gross_amount,
        net_amount=original.net_amount,
        fee_amount=original.fee_amount,
        tax_amount=original.tax_amount,
        source_type=original.dest_type,
        source_masked_ref=original.dest_masked_ref,
        dest_type=original.source_type,
        dest_masked_ref=original.source_masked_ref,
        gateway_provider=original.gateway_provider,
        idempotency_key=idempotency_key,
        entries=mirrored,
        status=TransactionStatus.PROCESSING,
        reverses_transaction_id=original.transaction_id,
        commit=False,
    )

    original.status = TransactionStatus.REVERSED
    original.failure_reason = str(reason)[:500]

    if commit:
        db.session.commit()

    return reversal


# ── Posting templates ──────────────────────────────────────────────────────
# The double-entry shape of each money movement, in one place, so a route never
# has to reason about debits and credits.

def entries_for_transfer_charge(principal, fee, gst, total_charged, card_ref, bank_ref):
    """
    Card charged for a credit-to-bank transfer (PRD AC-002).

    The card is charged principal + fee + GST. CashU owes the user the
    principal, keeps the fee as income, and holds the GST for the state.
    """
    return [
        {
            'account': Account.GATEWAY_RECEIVABLE,
            'debit': total_charged,
            'narration': f'Card charge {card_ref}',
        },
        {
            'account': Account.USER_PAYABLE,
            'credit': principal,
            'narration': f'Payable to {bank_ref}',
        },
        {
            'account': Account.FEE_INCOME,
            'credit': fee,
            'narration': 'Convenience fee',
        },
        {
            'account': Account.GST_PAYABLE,
            'credit': gst,
            'narration': 'GST on convenience fee',
        },
    ]


def entries_for_transfer_payout(principal, bank_ref):
    """Payout dispatched: the liability to the user becomes cash in transit."""
    return [
        {
            'account': Account.USER_PAYABLE,
            'debit': principal,
            'narration': f'Payout dispatched to {bank_ref}',
        },
        {
            'account': Account.PAYOUT_CLEARING,
            'credit': principal,
            'narration': 'IMPS payout in flight',
        },
    ]


def entries_for_emi_payment(amount, source_ref, biller_ref):
    """
    EMI collected from the user and owed onward to the biller.

    Note the source is never a credit card: RBI prohibits servicing loan debt
    from a revolving credit line (PRD 11.1), and emi_payments has no such
    payment mode in its vocabulary.
    """
    return [
        {
            'account': Account.GATEWAY_RECEIVABLE,
            'debit': amount,
            'narration': f'EMI collected from {source_ref}',
        },
        {
            'account': Account.BILLER_PAYABLE,
            'credit': amount,
            'narration': f'Payable to biller {biller_ref}',
        },
    ]


def entries_for_qr_payment(amount, payer_ref, payee_ref):
    """
    A scanned UPI payment to a merchant.

    CashU collects over UPI and owes the payee the same amount, so the entry is
    a clean pass-through: no fee, no GST, nothing retained. If a commercial
    model is added later it belongs here as a FEE_INCOME credit, not as an
    adjustment to either side of this pair.
    """
    return [
        {
            'account': Account.GATEWAY_RECEIVABLE,
            'debit': amount,
            'narration': f'UPI collection {payer_ref}',
        },
        {
            'account': Account.BILLER_PAYABLE,
            'credit': amount,
            'narration': f'Payable to {payee_ref}',
        },
    ]


def entries_for_penny_drop(amount, bank_ref):
    """The 1 INR verification debit - a real payout, so it is a real posting."""
    return [
        {
            'account': Account.GATEWAY_CHARGES,
            'debit': amount,
            'narration': f'Penny drop verification to {bank_ref}',
        },
        {
            'account': Account.PAYOUT_CLEARING,
            'credit': amount,
            'narration': 'Penny drop in flight',
        },
    ]


# ── Integrity ──────────────────────────────────────────────────────────────

def verify_balanced(transaction_id: str) -> tuple:
    """Check one transaction's entries sum to zero. Returns (ok, debit, credit)."""
    row = db.session.query(
        func.coalesce(func.sum(DoubleEntryLedger.debit_amount), 0),
        func.coalesce(func.sum(DoubleEntryLedger.credit_amount), 0),
    ).filter(DoubleEntryLedger.transaction_id == transaction_id).one()

    debit, credit = money(row[0]), money(row[1])
    return debit == credit, debit, credit


def self_audit(limit: int = 5000) -> dict:
    """
    Nightly integrity sweep - the mitigation for deviation D1.

    On MySQL the balancing guarantee lives in application code rather than the
    database's strictest isolation level, so it is verified rather than
    assumed. An UNBALANCED_LEDGER finding means post() was bypassed somewhere,
    which is a bug of the highest severity.
    """
    from portal.models.reconciliation import (
        DiscrepancyType, ReconciliationDiscrepancies,
    )

    unbalanced = db.session.query(
        DoubleEntryLedger.transaction_id,
        func.coalesce(func.sum(DoubleEntryLedger.debit_amount), 0).label('debits'),
        func.coalesce(func.sum(DoubleEntryLedger.credit_amount), 0).label('credits'),
    ).group_by(DoubleEntryLedger.transaction_id).having(
        func.coalesce(func.sum(DoubleEntryLedger.debit_amount), 0)
        != func.coalesce(func.sum(DoubleEntryLedger.credit_amount), 0)
    ).limit(limit).all()

    # A money-moving transaction with no journal entries at all is the other
    # way post() can have been bypassed.
    orphans = db.session.query(MasterTransactions.transaction_id).outerjoin(
        DoubleEntryLedger,
        MasterTransactions.transaction_id == DoubleEntryLedger.transaction_id,
    ).filter(
        DoubleEntryLedger.entry_id.is_(None),
        MasterTransactions.status.in_(
            [TransactionStatus.SUCCEEDED, TransactionStatus.PROCESSING]
        ),
    ).limit(limit).all()

    findings = []

    for txn_id, debits, credits in unbalanced:
        findings.append({
            'transaction_id': txn_id,
            'type': DiscrepancyType.UNBALANCED_LEDGER,
            'debits': float(debits),
            'credits': float(credits),
        })
        db.session.add(ReconciliationDiscrepancies(
            run_id=None,
            transaction_id=txn_id,
            discrepancy_type=DiscrepancyType.UNBALANCED_LEDGER,
            expected_amount=debits,
            actual_amount=credits,
            details=f'Ledger does not balance: Dr {debits} vs Cr {credits}',
        ))

    for (txn_id,) in orphans:
        findings.append({
            'transaction_id': txn_id,
            'type': DiscrepancyType.LEDGER_MISSING,
        })
        db.session.add(ReconciliationDiscrepancies(
            run_id=None,
            transaction_id=txn_id,
            discrepancy_type=DiscrepancyType.LEDGER_MISSING,
            details='Settled transaction has no double-entry ledger rows.',
        ))

    if findings:
        db.session.commit()

    return {
        'checked_at': utcnow().isoformat(),
        'unbalanced_count': len(unbalanced),
        'orphan_count': len(orphans),
        'healthy': not findings,
        'findings': findings[:100],
    }
