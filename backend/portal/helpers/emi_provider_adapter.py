"""
portal/helpers/emi_provider_adapter.py
======================================
Lender abstraction (PRD FR-007, section 10.1).

The PRD requires an EMIProviderAdapter interface so a new NBFC can be onboarded
without touching core code. Bajaj Finance is the anchor launch provider; HDB,
IDFC and Home Credit are Phase 1.1.

Two integration modes:
  BBPS        routed through a licensed Bharat Bill Payment Operating Unit
  DIRECT_API  the lender's own B2B API

Neither is signed yet (PRD open decision 2), so both resolve to a simulator that
returns realistic loan data and can be told to fail - ERR-010 (biller offline)
is otherwise untestable.
"""

import hashlib
import random
from datetime import date, timedelta
from decimal import Decimal

from flask import current_app

from portal.helpers.adapters import Simulate, _simulating, _ref, _use_sandbox


class EMIProviderError(Exception):
    def __init__(self, message: str, code: str = 'PROVIDER_ERROR', retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


PREDEFINED_TEST_LOANS = {
    'LAN4567890': {
        'emi_amount': Decimal('3500.00'),
        'due_day_of_month': 5,
        'total_tenure': 12,
        'tenure_remaining': 8,
        'total_loan_amount': Decimal('42000.00'),
        'outstanding_bal': Decimal('28000.00'),
        'interest_rate': Decimal('13.50'),
        'loan_type': 'CONSUMER_DURABLE',
    },
    'BAJAJ123456': {
        'emi_amount': Decimal('4200.00'),
        'due_day_of_month': 10,
        'total_tenure': 18,
        'tenure_remaining': 12,
        'total_loan_amount': Decimal('75600.00'),
        'outstanding_bal': Decimal('50400.00'),
        'interest_rate': Decimal('14.00'),
        'loan_type': 'PERSONAL_LOAN',
    },
    'HDB987654': {
        'emi_amount': Decimal('2800.00'),
        'due_day_of_month': 15,
        'total_tenure': 9,
        'tenure_remaining': 5,
        'total_loan_amount': Decimal('25200.00'),
        'outstanding_bal': Decimal('14000.00'),
        'interest_rate': Decimal('12.50'),
        'loan_type': 'TWO_WHEELER',
    },
    'IDFC112233': {
        'emi_amount': Decimal('5500.00'),
        'due_day_of_month': 20,
        'total_tenure': 24,
        'tenure_remaining': 16,
        'total_loan_amount': Decimal('132000.00'),
        'outstanding_bal': Decimal('88000.00'),
        'interest_rate': Decimal('15.00'),
        'loan_type': 'PERSONAL_LOAN',
    },
    'HC123456': {
        'emi_amount': Decimal('2100.00'),
        'due_day_of_month': 12,
        'total_tenure': 12,
        'tenure_remaining': 7,
        'total_loan_amount': Decimal('25200.00'),
        'outstanding_bal': Decimal('14700.00'),
        'interest_rate': Decimal('16.00'),
        'loan_type': 'CONSUMER_DURABLE',
    },
    'TVS123456': {
        'emi_amount': Decimal('3200.00'),
        'due_day_of_month': 7,
        'total_tenure': 24,
        'tenure_remaining': 18,
        'total_loan_amount': Decimal('76800.00'),
        'outstanding_bal': Decimal('57600.00'),
        'interest_rate': Decimal('13.00'),
        'loan_type': 'TWO_WHEELER',
    },
    'TC123456': {
        'emi_amount': Decimal('6000.00'),
        'due_day_of_month': 1,
        'total_tenure': 36,
        'tenure_remaining': 28,
        'total_loan_amount': Decimal('216000.00'),
        'outstanding_bal': Decimal('168000.00'),
        'interest_rate': Decimal('11.50'),
        'loan_type': 'PERSONAL_LOAN',
    },
}


def _lookup_loan_from_db(provider_id: int, loan_account_no: str):
    """
    Look up loan account from the EMIObligations database table.
    """
    try:
        from portal.models.emi_obligations import EMIObligations
        from portal.helpers.encryption import decrypt

        clean_lan = loan_account_no.strip().upper()
        if len(clean_lan) < 4:
            return None

        candidates = EMIObligations.query.filter_by(
            provider_id=provider_id,
            loan_account_last4=clean_lan[-4:],
        ).all()

        for cand in candidates:
            try:
                decrypted = decrypt(cand.loan_account_no_enc)
                if decrypted.strip().upper() == clean_lan:
                    due_day = cand.due_day_of_month or 5
                    return {
                        'emi_amount': cand.emi_amount,
                        'due_day_of_month': due_day,
                        'total_tenure': cand.total_tenure or 12,
                        'tenure_remaining': cand.tenure_remaining or 12,
                        'total_loan_amount': cand.total_loan_amount or (cand.emi_amount * (cand.total_tenure or 12)),
                        'outstanding_bal': cand.outstanding_bal or (cand.emi_amount * (cand.tenure_remaining or 12)),
                        'interest_rate': cand.interest_rate or Decimal('14.00'),
                        'next_due_date': cand.next_due_date or next_due_date(due_day),
                        'loan_type': cand.loan_type if isinstance(cand.loan_type, str) else getattr(cand.loan_type, 'value', 'CONSUMER_DURABLE'),
                    }
            except Exception:
                continue
    except Exception:
        pass
    return None


def fetch_loan(*, provider, loan_account_no: str, registered_phone: str = None) -> dict:
    """
    Look up a loan with the lender (PRD FR-007 step: invoke BBPS or the provider adapter).

    Returns {ok, data} or {ok: False, error, code}.
    Never generates random values. Only returns data if the loan exists in the database
    or belongs to predefined test loan accounts.
    """
    clean_lan = (loan_account_no or '').strip().upper()

    if not provider.supports_auto_fetch and provider.integration_mode == 'MANUAL':
        return {
            'ok': False,
            'code': 'MANUAL_ONLY',
            'error': 'This provider does not support automatic lookup. '
                     'Please enter your loan details manually.',
        }

    if _use_sandbox():
        if _simulating(clean_lan, Simulate.BILLER_DOWN):
            return {
                'ok': False,
                'code': 'ERR-010',
                'error': f'{provider.display_name} biller system is temporarily '
                         'offline. Please try again in 30 minutes.',
                'retryable': True,
            }

        if len(clean_lan) < 4:
            return {
                'ok': False,
                'code': 'INVALID_LAN',
                'error': 'Loan account not found. Please enter a valid loan account number.',
            }

        # 1. Search database EMIObligations
        db_loan = _lookup_loan_from_db(provider.provider_id, clean_lan)
        if db_loan:
            return {
                'ok': True,
                'data': db_loan,
                'provider_reference': _ref('bbps_db'),
            }

        # 2. Check predefined test loan accounts
        if clean_lan in PREDEFINED_TEST_LOANS:
            preset = PREDEFINED_TEST_LOANS[clean_lan]
            due_day = preset['due_day_of_month']
            return {
                'ok': True,
                'data': {
                    'emi_amount': preset['emi_amount'],
                    'due_day_of_month': due_day,
                    'total_tenure': preset['total_tenure'],
                    'tenure_remaining': preset['tenure_remaining'],
                    'total_loan_amount': preset['total_loan_amount'],
                    'outstanding_bal': preset['outstanding_bal'],
                    'interest_rate': preset['interest_rate'],
                    'next_due_date': next_due_date(due_day),
                    'loan_type': preset['loan_type'],
                },
                'provider_reference': _ref('bbps_sbx'),
            }

        # 3. Not found
        return {
            'ok': False,
            'code': 'LOAN_NOT_FOUND',
            'error': 'Loan account not found. Please enter a valid loan account number.',
        }

    return {
        'ok': False,
        'code': 'PROVIDER_NOT_CONFIGURED',
        'error': 'No BBPS operating unit is configured for this provider.',
    }


def submit_payment(
    *,
    provider,
    loan_account_no: str,
    amount,
    reference: str,
    payment_mode: str,
) -> dict:
    """
    Route a collected payment to the lender through BBPS (PRD FR-008).

    Called only after the money is actually collected from the user's bank -
    telling a biller a payment was made before it settles creates a receivable
    nobody can reconcile.
    """
    if _use_sandbox():
        if _simulating(reference, Simulate.BILLER_DOWN):
            return {
                'ok': False,
                'code': 'ERR-010',
                'error': f'{provider.display_name} biller system is temporarily '
                         'offline. Please try again in 30 minutes.',
                'retryable': True,
            }

        return {
            'ok': True,
            'bbps_rrn': f'{random.randint(10 ** 11, 10 ** 12 - 1)}',
            'biller_ack_utr': _ref('ack_sbx'),
            'status': 'SUCCESS',
        }

    return {
        'ok': False,
        'code': 'PROVIDER_NOT_CONFIGURED',
        'error': 'No BBPS operating unit is configured for this provider.',
    }


def poll_payment(*, provider, reference: str) -> dict:
    """
    Ask the biller whether a submitted payment cleared.

    Drives the PRD FR-008 polling worker: a bank debit can succeed while the
    biller acknowledgement lags, and the payment stays PENDING until this
    resolves or 24 hours pass.
    """
    if _use_sandbox():
        return {'ok': True, 'status': 'SUCCESS', 'bbps_rrn': reference}

    return {'ok': False, 'error': 'Biller polling is not configured.'}


def next_due_date(due_day: int, after: date = None) -> date:
    """
    The next occurrence of a monthly due day.

    Clamped to 28 so a loan due on the 31st does not vanish in February.
    """
    after = after or date.today()
    day = min(int(due_day), 28)

    if after.day < day:
        return after.replace(day=day)

    month = after.month + 1
    year = after.year
    if month > 12:
        month, year = 1, year + 1
    return date(year, month, day)
