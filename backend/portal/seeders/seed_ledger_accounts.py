"""
Seed the chart of accounts (PRD FR-010).

ledger_engine rejects any posting naming an account code absent from this table,
so this seeder must run before anything can move money. That check is what stops
a typo in an account code from creating a silent orphan entry that only surfaces
as a reconciliation discrepancy days later.
"""

import logging

from portal import db
from portal.helpers.ledger_engine import Account
from portal.models.ledger_accounts import AccountClass, LedgerAccounts

logger = logging.getLogger('cashu')

# (code, name, class, normal balance, description)
ACCOUNTS = [
    (Account.GATEWAY_RECEIVABLE, 'Gateway Receivable', AccountClass.ASSET, 'DEBIT',
     'Funds charged to a card but not yet settled by the payment aggregator.'),
    (Account.PAYOUT_CLEARING, 'Payout Clearing', AccountClass.ASSET, 'DEBIT',
     'Funds handed to the payout partner and in flight to a beneficiary.'),
    (Account.USER_PAYABLE, 'User Payable', AccountClass.LIABILITY, 'CREDIT',
     'Principal owed to a user between the card charge and the bank credit.'),
    (Account.BILLER_PAYABLE, 'Biller Payable', AccountClass.LIABILITY, 'CREDIT',
     'EMI collected from a user and owed onward to the lender.'),
    (Account.FEE_INCOME, 'Convenience Fee Income', AccountClass.INCOME, 'CREDIT',
     'Platform convenience fee earned on transfers.'),
    (Account.GST_PAYABLE, 'GST Payable', AccountClass.LIABILITY, 'CREDIT',
     'GST collected on the convenience fee and owed to the tax authority.'),
    (Account.GATEWAY_CHARGES, 'Gateway Charges', AccountClass.EXPENSE, 'DEBIT',
     'MDR and per-transaction costs paid to payment partners.'),
    (Account.REVERSAL_CLEARING, 'Reversal Clearing', AccountClass.ASSET, 'DEBIT',
     'Refunds dispatched to a source card and not yet confirmed.'),
    (Account.SUSPENSE, 'Suspense', AccountClass.ASSET, 'DEBIT',
     'Unmatched amounts held pending manual reconciliation.'),
]


def seed_ledger_accounts():
    created = 0

    for code, name, account_class, normal_balance, description in ACCOUNTS:
        if not LedgerAccounts.query.filter_by(account_code=code).first():
            db.session.add(LedgerAccounts(
                account_code=code,
                account_name=name,
                account_class=account_class,
                normal_balance=normal_balance,
                description=description,
                is_active=True,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_ledger_accounts: created {created} account(s).')
