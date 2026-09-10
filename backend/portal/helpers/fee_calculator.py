"""
portal/helpers/fee_calculator.py
================================
Transfer pricing (PRD 9.2, acceptance criterion AC-002).

    Convenience fee = principal x fee%          (default 1.95%)
    GST             = fee x 18%                 (on the FEE ONLY, never the principal)
    Charged to card = principal + fee + GST
    Disbursed       = principal

The GST base is the single easiest thing to get wrong here, and getting it
wrong overcharges every customer: GST applies to the service fee, not to the
money being moved. AC-002 pins the arithmetic - 10,000 principal at 2% gives
200 fee, 36 GST, 10,236 charged, 10,000 disbursed.

Everything is Decimal. A binary float cannot represent 0.01 exactly, and on a
fee calculation that error is real money.
"""

from decimal import Decimal, ROUND_HALF_UP

from portal.helpers import settings
from portal.helpers.settings import Key


def _q(value) -> Decimal:
    """Round to paise the way the Numeric(12,2) columns store it."""
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_transfer_fee(principal, fee_percent=None, gst_percent=None) -> dict:
    """
    Full fee breakdown for a transfer.

    Returned verbatim to the confirmation screen, which PRD 9.2 requires to be
    a non-skippable disclosure shown before the 3DS challenge - the user must
    see exactly what the card will be charged before they authorise it.
    """
    principal = _q(principal)

    if fee_percent is None:
        fee_percent = settings.get_decimal(Key.TRANSFER_CONVENIENCE_FEE_PERCENT)
    if gst_percent is None:
        gst_percent = settings.get_decimal(Key.GST_PERCENT)

    fee_percent = Decimal(str(fee_percent))
    gst_percent = Decimal(str(gst_percent))

    convenience_fee = _q(principal * fee_percent / Decimal('100'))
    gst_on_fee = _q(convenience_fee * gst_percent / Decimal('100'))
    total_charged = _q(principal + convenience_fee + gst_on_fee)

    return {
        'principal_amount': principal,
        'convenience_fee': convenience_fee,
        'gst_on_fee': gst_on_fee,
        'total_charged_to_card': total_charged,
        'net_payout_amount': principal,          # the user receives the principal
        'fee_percentage_applied': fee_percent,
        'gst_percentage_applied': gst_percent,
        'breakdown': [
            {'label': 'Principal Amount', 'amount': principal, 'emphasis': False},
            {
                'label': f'Convenience Fee ({fee_percent}%)',
                'amount': convenience_fee,
                'emphasis': False,
            },
            {
                'label': f'GST on Fee ({gst_percent}%)',
                'amount': gst_on_fee,
                'emphasis': False,
            },
            {'label': 'Total Charged to Card', 'amount': total_charged, 'emphasis': True},
            {'label': 'Net Disbursed to Bank', 'amount': principal, 'emphasis': True},
        ],
    }


def as_floats(breakdown: dict) -> dict:
    """JSON-safe view of calculate_transfer_fee() for the API layer."""
    out = {}
    for key, value in breakdown.items():
        if key == 'breakdown':
            out[key] = [
                {
                    'label': row['label'],
                    'amount': float(row['amount']),
                    'emphasis': row['emphasis'],
                }
                for row in value
            ]
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def mandate_cap(emi_amount) -> Decimal:
    """
    Minimum permissible auto-pay mandate ceiling (PRD 12.3).

    Set to 110% of the EMI by default: high enough to absorb a small interest
    adjustment without bouncing the debit, low enough that the mandate is not a
    blank cheque against the user's account.
    """
    multiplier = settings.get_decimal(Key.MANDATE_CAP_MULTIPLIER)
    return _q(Decimal(str(emi_amount)) * multiplier)
