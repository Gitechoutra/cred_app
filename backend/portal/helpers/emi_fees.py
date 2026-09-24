"""
portal/helpers/emi_fees.py
==========================
The one pricing rule the EMI product still needs.

Rehomed from fee_calculator, which priced credit-to-bank transfers and went
with that product. A mandate ceiling bounds an NPCI auto-pay mandate and has
nothing to do with transfer pricing, so this is not a leftover.
"""

from decimal import Decimal, ROUND_HALF_UP

from portal.helpers import settings
from portal.helpers.settings import Key


def mandate_cap(emi_amount) -> Decimal:
    """
    Minimum permissible auto-pay mandate ceiling (PRD 12.3).

    Set to 110% of the EMI by default: high enough to absorb a small interest
    adjustment without bouncing the debit, low enough that the mandate is not a
    blank cheque against the user's account.
    """
    multiplier = settings.get_decimal(Key.MANDATE_CAP_MULTIPLIER)
    return _q(Decimal(str(emi_amount)) * multiplier)
