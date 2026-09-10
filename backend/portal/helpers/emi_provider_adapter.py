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


def _deterministic_loan(loan_account_no: str, provider_name: str) -> dict:
    """
    Derive stable pseudo-loan details from the LAN.

    Deterministic on purpose: the same LAN must return the same EMI and tenure
    on every lookup, or the sandbox would show a different loan each time the
    user opened the screen.
    """
    seed = int(hashlib.sha256(
        f'{provider_name}:{loan_account_no}'.encode()
    ).hexdigest()[:12], 16)
    rng = random.Random(seed)

    emi_amount = Decimal(rng.choice([1499, 2100, 3100, 4250, 5600, 7800, 12500]))
    total_tenure = rng.choice([6, 9, 12, 18, 24, 36])
    tenure_remaining = rng.randint(1, total_tenure)
    due_day = rng.choice([1, 5, 10, 12, 15, 20, 25, 28])

    total_loan = emi_amount * total_tenure
    outstanding = emi_amount * tenure_remaining

    today = date.today()
    if today.day < due_day:
        next_due = today.replace(day=min(due_day, 28))
    else:
        month = today.month + 1
        year = today.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        next_due = date(year, month, min(due_day, 28))

    return {
        'emi_amount': emi_amount,
        'due_day_of_month': due_day,
        'total_tenure': total_tenure,
        'tenure_remaining': tenure_remaining,
        'total_loan_amount': total_loan,
        'outstanding_bal': outstanding,
        'interest_rate': Decimal(str(rng.choice([12.5, 13.99, 15.0, 16.5, 18.0]))),
        'next_due_date': next_due,
        'loan_type': rng.choice(
            ['CONSUMER_DURABLE', 'PERSONAL_LOAN', 'TWO_WHEELER']
        ),
    }


def fetch_loan(*, provider, loan_account_no: str, registered_phone: str = None) -> dict:
    """
    Look up a loan with the lender (PRD FR-007 step: invoke BBPS or the
    provider adapter).

    Returns {ok, data} or {ok: False, error, code}. A lookup failure is a normal
    outcome - a mistyped LAN is the single most common thing that happens on
    this screen - so it is returned rather than raised.
    """
    if not provider.supports_auto_fetch and provider.integration_mode == 'MANUAL':
        return {
            'ok': False,
            'code': 'MANUAL_ONLY',
            'error': 'This provider does not support automatic lookup. '
                     'Please enter your loan details manually.',
        }

    if _use_sandbox():
        if _simulating(loan_account_no, Simulate.BILLER_DOWN):
            return {
                'ok': False,
                'code': 'ERR-010',
                'error': f'{provider.display_name} biller system is temporarily '
                         'offline. Please try again in 30 minutes.',
                'retryable': True,
            }

        # PRD ERR-010 sibling case: an LAN the lender does not recognise.
        if len(loan_account_no) < 6:
            return {
                'ok': False,
                'code': 'INVALID_LAN',
                'error': 'Provider rejected this loan account number. Please '
                         'verify the LAN on your loan sanction letter.',
            }

        return {
            'ok': True,
            'data': _deterministic_loan(loan_account_no, provider.provider_name),
            'provider_reference': _ref('bbps_sbx'),
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
