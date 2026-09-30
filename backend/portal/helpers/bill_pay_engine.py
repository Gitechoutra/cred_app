"""
portal/helpers/bill_pay_engine.py
=================================
Pay Bills: credit drawn for a declared, eligible bill and paid out to the
holder's own verified bank account.

⚑ Regulatory posture. This is a credit-to-bank movement - the thing Version1.md
section 2 removed on 2026-09-24 as disguised cash cycling - reinstated on
2026-09-30 at the product owner's request. It is built as a regulated
transaction rather than a transfer screen, and it runs on the sandbox payout
rail only: adapters.dispatch_payout refuses in live mode until a licensed
issuing/PA partner signs off the merchant model (PRD open decision #1).

The controls, each enforced here and not in the browser:

    eligibility     KYC done, credit line ACTIVE, transactions not frozen
    declaration     category, biller, bill reference and a purpose that matches
                    the category; "Other" needs a written description
    destination     the holder's own account, penny-drop VERIFIED
    limits          min/max per bill, requests per day, full KYC above a
                    threshold, and the credit line's own available credit and
                    daily/monthly spend caps (checked under lock at the draw)
    disclosure      fee and GST priced by the server and shown before consent;
                    the consent timestamp and disclosure version are stored
    authentication  a TRANSACTION OTP to the registered mobile, single use
    tracking        PROCESSING -> SUCCEEDED | PENDING | FAILED, and REVERSED
                    when the bank returns a completed payout
    reversal        any payout that does not complete gives back the whole draw,
                    fee and GST included

Lifecycle:

    create()   validates and prices the request, records it AWAITING_OTP and
               sends the OTP. Nothing touches the credit line.
    confirm()  verifies the OTP, draws the credit (credit_engine), hands the
               payout to the rail, and records what the rail said.
    refresh()  asks the rail about a payout still in flight, or one recently
               completed that the bank may yet return. Run by the poller and by
               the status endpoint.
"""

import secrets
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from flask import current_app

from portal import db
from portal.helpers import adapters, audit, credit_engine, ledger_engine, otp, settings
from portal.helpers.encryption import decrypt
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import money
from portal.helpers.settings import Key
from portal.models.bank_accounts import BankAccounts
from portal.models.base import utcnow
from portal.models.bill_payments import (
    BillCategory, BillPayments, BillPaymentStatus, BillPurpose,
)
from portal.models.credit_accounts import CreditAccountStatus
from portal.models.credit_transactions import (
    CreditTransactions, CreditTransactionStatus, CreditTransactionType,
    MerchantCategory,
)
from portal.models.master_transactions import MasterTransactions, TransactionStatus
from portal.models.otp_verifications import OTPPurpose
from portal.models.users import KYCTier

ZERO = Decimal('0.00')

#: The wording of the Pay Bills disclosure the holder accepts. Bumped whenever
#: the consent text on the review screen changes, so every row records which
#: version was agreed to.
DISCLOSURE_VERSION = 'PB-2026-09-30'

#: The exact sentence the holder ticks. Served to the client so the words shown
#: and the words recorded cannot drift apart.
CONSENT_TEXT = (
    'I confirm that the information provided is accurate and this payment is '
    'for a genuine eligible expense.'
)

#: How long an OTP-pending request stays confirmable. Longer than the OTP
#: itself so a resend does not strand the request; shorter than a session, so a
#: priced quote is not accepted long after the fee may have changed.
REQUEST_TTL = timedelta(minutes=15)

#: How long after completion a payout is still checked for a bank return.
RETURN_WINDOW = timedelta(hours=72)

#: Which purposes are coherent with which bill. The purpose is asked for
#: separately so a mismatch is caught, not assumed away.
ALLOWED_PURPOSES = {
    BillCategory.ELECTRICITY: [BillPurpose.ELECTRICITY],
    BillCategory.WATER: [BillPurpose.WATER],
    BillCategory.GAS: [BillPurpose.OTHER],
    BillCategory.BROADBAND: [BillPurpose.BROADBAND],
    BillCategory.MOBILE_POSTPAID: [BillPurpose.MOBILE],
    BillCategory.DTH: [BillPurpose.OTHER],
    BillCategory.INSURANCE: [BillPurpose.INSURANCE],
    BillCategory.EDUCATION: [BillPurpose.EDUCATION],
    BillCategory.RENT: [BillPurpose.RENT],
    BillCategory.MEDICAL: [BillPurpose.MEDICAL],
    BillCategory.OTHER: [BillPurpose.OTHER],
}

#: How a bill is categorised on the credit line's statement.
_MERCHANT_CATEGORY = {
    BillCategory.ELECTRICITY: MerchantCategory.UTILITIES,
    BillCategory.WATER: MerchantCategory.UTILITIES,
    BillCategory.GAS: MerchantCategory.UTILITIES,
    BillCategory.BROADBAND: MerchantCategory.UTILITIES,
    BillCategory.MOBILE_POSTPAID: MerchantCategory.UTILITIES,
    BillCategory.DTH: MerchantCategory.UTILITIES,
    BillCategory.INSURANCE: MerchantCategory.OTHER,
    BillCategory.EDUCATION: MerchantCategory.EDUCATION,
    BillCategory.RENT: MerchantCategory.OTHER,
    BillCategory.MEDICAL: MerchantCategory.HEALTHCARE,
    BillCategory.OTHER: MerchantCategory.OTHER,
}


class BillPayError(Exception):
    """A refusal the holder should see, with a code the client can branch on."""

    def __init__(self, code: str, message: str, recovery: str = None,
                 field: str = None, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery
        self.field = field
        self.status = status


# ── Pricing ────────────────────────────────────────────────────────────────

def quote(bill_amount) -> dict:
    """
    Fee and GST on a bill. The only place Pay Bills is priced.

    GST is charged on the fee, never on the bill. Both are rounded half-up to
    the paisa, the same way the ledger stores them.
    """
    bill_amount = money(bill_amount)
    fee_percent = money(settings.get_decimal(Key.BILL_PAY_FEE_PERCENT))
    gst_percent = money(settings.get_decimal(Key.GST_PERCENT))
    fee = money(bill_amount * fee_percent / 100)
    gst = money(fee * gst_percent / 100)
    return {
        'bill_amount': bill_amount,
        'fee_percent': fee_percent,
        'gst_percent': gst_percent,
        'fee': fee,
        'gst': gst,
        'total': bill_amount + fee + gst,
    }


def _max_bill_for(headroom: Decimal) -> Decimal:
    """The largest bill whose total, fee and GST included, fits `headroom`."""
    if headroom <= ZERO:
        return ZERO
    fee_percent = money(settings.get_decimal(Key.BILL_PAY_FEE_PERCENT))
    gst_percent = money(settings.get_decimal(Key.GST_PERCENT))
    factor = 1 + fee_percent / 100 * (1 + gst_percent / 100)
    candidate = (headroom / factor).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    # Rounding the fee half-up can push the total a paisa over; step back.
    while candidate > ZERO and quote(candidate)['total'] > headroom:
        candidate -= Decimal('0.01')
    return max(candidate, ZERO)


# ── Eligibility ────────────────────────────────────────────────────────────

def _spent_since(account, since) -> Decimal:
    """Credit drawn since `since` - the same sum the spend caps are checked on."""
    total = db.session.query(
        db.func.coalesce(db.func.sum(CreditTransactions.amount), 0)
    ).filter(
        CreditTransactions.credit_account_id == account.credit_account_id,
        CreditTransactions.transaction_type == CreditTransactionType.PURCHASE,
        CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
        CreditTransactions.created_on >= since,
    ).scalar()
    return money(total)


def _requests_today(user_id: str) -> int:
    """Pay Bills requests that drew credit today (UTC day, like the spend caps)."""
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return BillPayments.query.filter(
        BillPayments.user_id == user_id,
        BillPayments.created_on >= day_start,
        BillPayments.otp_verified_at.isnot(None),
    ).count()


def verified_banks(user) -> list:
    """The holder's own accounts that may receive a payout, primary first."""
    rows = BankAccounts.query.filter_by(
        user_id=user.user_id, is_active=True, deleted_at=None,
    ).all()
    eligible = [row for row in rows if row.is_payout_eligible]
    return sorted(eligible, key=lambda r: (not r.is_primary, r.created_on))


def eligibility(user) -> dict:
    """
    Everything the Pay Bills screen shows before the holder types anything,
    and every reason they cannot proceed.

    `blockers` is ordered: the first one is the next thing to fix. The amount
    available for bill payment is the smallest of the headrooms - available
    credit, the daily and monthly spend caps, and the per-bill maximum - after
    fee and GST, so the figure shown is a bill that will actually go through.
    """
    now = utcnow()
    account = credit_engine.account_for(user.user_id)
    banks = verified_banks(user)

    minimum = money(settings.get_decimal(Key.BILL_PAY_MIN_AMOUNT))
    maximum = money(settings.get_decimal(Key.BILL_PAY_MAX_PER_TXN))
    per_day = settings.get_int(Key.BILL_PAY_MAX_PER_DAY)
    full_kyc_above = money(settings.get_decimal(Key.BILL_PAY_FULL_KYC_ABOVE))
    used_today = _requests_today(user.user_id)

    blockers = []

    def block(code, message, action=None):
        blockers.append({'code': code, 'message': message, 'action': action})

    if user.kyc_tier == KYCTier.NONE:
        block('KYC_REQUIRED', 'Complete KYC verification to use Pay Bills.', 'KYC')
    if user.transactions_frozen_until and user.transactions_frozen_until > now:
        block('TRANSACTIONS_FROZEN',
              'Payments are paused on your account after a recent security change.')
    if account is None:
        block('NO_CREDIT_LINE', 'Pay Bills uses your CashU credit line. Apply for one first.',
              'APPLY')
    elif account.status != CreditAccountStatus.ACTIVE:
        block('CREDIT_NOT_ACTIVE', {
            CreditAccountStatus.PENDING_PURPOSE: 'Declare the purpose of your credit line first.',
            CreditAccountStatus.PENDING_ACTIVATION: 'Activate your credit card first.',
            CreditAccountStatus.BLOCKED: 'Your credit card is frozen. Unfreeze it to pay bills.',
        }.get(account.status, 'Your credit line cannot be used right now.'), 'CREDIT')
    if not banks:
        block('NO_VERIFIED_BANK', 'No verified bank account available.', 'ADD_BANK')
    if used_today >= per_day:
        block('DAILY_REQUESTS_EXHAUSTED',
              f'You have used all {per_day} Pay Bills requests for today. '
              'Try again tomorrow.')
    if adapters.payout_provider() != 'SANDBOX' or not credit_engine.simulator_allowed():
        block('PAYOUT_RAIL_UNAVAILABLE',
              'Pay Bills is not available yet. Bank payouts are awaiting partner approval.')

    available = limit = ZERO
    for_bills = ZERO
    if account is not None:
        available = money(account.available_credit)
        limit = money(account.credit_limit)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        headroom = min(
            available,
            money(settings.get_decimal(Key.CREDIT_DAILY_SPEND_LIMIT))
            - _spent_since(account, day_start),
            money(settings.get_decimal(Key.CREDIT_MONTHLY_SPEND_LIMIT))
            - _spent_since(account, month_start),
        )
        for_bills = min(_max_bill_for(headroom), maximum)
        if user.kyc_tier != KYCTier.FULL:
            for_bills = min(for_bills, full_kyc_above)
        if for_bills < minimum:
            for_bills = ZERO
            if account.status == CreditAccountStatus.ACTIVE:
                block('NO_AVAILABLE_CREDIT',
                      'You do not have enough available credit for a bill payment. '
                      'Paying your card bill frees it up.', 'PAY_CARD_BILL')

    sample = quote(for_bills if for_bills > ZERO else Decimal('10000'))

    return {
        'eligible': not blockers,
        'blockers': blockers,
        'kyc_tier': user.kyc_tier,
        'credit_limit': limit,
        'available_credit': available,
        'available_for_bills': for_bills,
        'min_amount': minimum,
        'max_amount': maximum,
        'full_kyc_above': full_kyc_above,
        'requests_per_day': per_day,
        'requests_left_today': max(0, per_day - used_today),
        'fee_percent': sample['fee_percent'],
        'gst_percent': sample['gst_percent'],
        'masked_mobile': user.masked_phone(),
        'banks': banks,
        'sandbox': adapters.payout_provider() == 'SANDBOX',
        'disclosure_version': DISCLOSURE_VERSION,
        'consent_text': CONSENT_TEXT,
    }


# ── Create ─────────────────────────────────────────────────────────────────

def _new_reference() -> str:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    for _ in range(5):
        ref = 'CASHU' + ''.join(secrets.choice(alphabet) for _ in range(10))
        if not BillPayments.query.filter_by(reference=ref).first():
            return ref
    raise BillPayError(ErrorCode.INTERNAL_ERROR, 'Could not start this payment. Try again.')


def bank_display(bank: BankAccounts, bank_name: str = None) -> str:
    return f'{bank_name or bank.bank_name or "Bank"} •••• {bank.account_last4}'


def create(*, user, category: str, provider: str, bill_reference: str,
           purpose: str, purpose_note: str, amount, bank_account_id: str,
           consent: bool, idempotency_key: str, bank_name: str = None,
           ip: str = None, device: str = None) -> tuple:
    """
    Record a priced, consented Pay Bills request and send its OTP.

    Returns (record, otp_info). Touches no balance: the draw waits for the OTP.
    Validation here is the authoritative copy of what the form checks.
    """
    existing = BillPayments.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        if existing.user_id != user.user_id:
            raise BillPayError(ErrorCode.CONFLICT, 'Duplicate request.', status=409)
        return existing, None

    state = eligibility(user)
    if state['blockers']:
        first = state['blockers'][0]
        raise BillPayError(first['code'], first['message'], status=403)

    if category not in BillCategory.CHOICES:
        raise BillPayError(ErrorCode.VALIDATION_ERROR, 'Choose a bill category.', field='category')

    if category == BillCategory.OTHER or category not in BillCategory.PROVIDERS:
        if len(provider) < 3:
            raise BillPayError(ErrorCode.VALIDATION_ERROR,
                               'Enter who the bill is from.', field='provider')
    elif provider not in BillCategory.PROVIDERS[category]:
        raise BillPayError(ErrorCode.VALIDATION_ERROR,
                           'Choose a provider from the list.', field='provider')

    if not (4 <= len(bill_reference) <= 40) or not all(
        ch.isalnum() or ch in '-/ ' for ch in bill_reference
    ):
        raise BillPayError(
            ErrorCode.VALIDATION_ERROR,
            'Enter the bill or reference number exactly as printed on the bill '
            '(4-40 letters, digits, - or /).',
            field='bill_reference',
        )

    if purpose not in BillPurpose.CHOICES:
        raise BillPayError(ErrorCode.VALIDATION_ERROR, 'Choose the purpose of payment.',
                           field='purpose')
    if purpose not in ALLOWED_PURPOSES[category]:
        allowed = ', '.join(BillPurpose.LABELS[p] for p in ALLOWED_PURPOSES[category])
        raise BillPayError(
            ErrorCode.VALIDATION_ERROR,
            f'The purpose must match the bill you are paying. For '
            f'{BillCategory.LABELS[category]} choose: {allowed}.',
            field='purpose',
        )
    if purpose == BillPurpose.OTHER:
        if len(purpose_note) < 10:
            raise BillPayError(ErrorCode.VALIDATION_ERROR,
                               'Please describe the payment purpose (at least 10 characters).',
                               field='purpose_note')
    else:
        purpose_note = None

    amount = money(amount)
    if amount < state['min_amount']:
        raise BillPayError(ErrorCode.VALIDATION_ERROR,
                           f'The smallest bill you can pay is Rs. {state["min_amount"]:,.2f}.',
                           field='amount')
    if amount > state['max_amount']:
        raise BillPayError(ErrorCode.LIMIT_EXCEEDED,
                           f'The largest bill you can pay is Rs. {state["max_amount"]:,.2f}.',
                           field='amount')
    if user.kyc_tier != KYCTier.FULL and amount > state['full_kyc_above']:
        raise BillPayError(
            ErrorCode.KYC_REQUIRED,
            f'Bills above Rs. {state["full_kyc_above"]:,.2f} need full KYC.',
            recovery='Upgrade to full KYC from your profile, or pay a smaller amount.',
            field='amount', status=403,
        )
    priced = quote(amount)
    if amount > state['available_for_bills']:
        raise BillPayError(
            'INSUFFICIENT_CREDIT',
            f'This bill needs Rs. {priced["total"]:,.2f} including fees. You can pay '
            f'up to Rs. {state["available_for_bills"]:,.2f} right now.',
            recovery='Enter a smaller amount, or pay your card bill to free up credit.',
            field='amount',
        )

    bank = next((b for b in state['banks'] if b.bank_account_id == bank_account_id), None)
    if bank is None:
        raise BillPayError(
            ErrorCode.ACCOUNT_NOT_VERIFIED,
            'Choose one of your verified bank accounts.',
            recovery='Only your own penny-drop verified accounts can receive a payout.',
            field='bank_account_id',
        )

    if not consent:
        raise BillPayError(ErrorCode.VALIDATION_ERROR,
                           'Please confirm the declaration before continuing.',
                           field='consent')

    account = credit_engine.account_for(user.user_id)
    now = utcnow()

    # One live request at a time: an earlier unconfirmed one is superseded, so
    # an OTP can never authorise a quote the holder has since changed.
    BillPayments.query.filter_by(
        user_id=user.user_id, status=BillPaymentStatus.AWAITING_OTP,
    ).update({'status': BillPaymentStatus.CANCELLED,
              'failure_reason': 'Superseded by a newer request.'})

    record = BillPayments(
        reference=_new_reference(),
        user_id=user.user_id,
        credit_account_id=account.credit_account_id,
        bank_account_id=bank.bank_account_id,
        status=BillPaymentStatus.AWAITING_OTP,
        category=category,
        provider=provider[:120],
        bill_reference_number=bill_reference[:50],
        purpose=purpose,
        purpose_note=purpose_note,
        bill_amount=priced['bill_amount'],
        fee_percent=priced['fee_percent'],
        fee_amount=priced['fee'],
        gst_amount=priced['gst'],
        total_amount=priced['total'],
        bank_display=bank_display(bank, bank_name),
        consent_at=now,
        disclosure_version=DISCLOSURE_VERSION,
        idempotency_key=idempotency_key,
        ip_address=ip,
        device_uuid=device,
    )
    db.session.add(record)
    db.session.commit()

    audit.record(
        action='BILL_PAY_REQUESTED',
        entity_type='BillPayments',
        entity_id=record.bill_payment_id,
        actor_user_id=user.user_id,
        after={
            'reference': record.reference,
            'category': category,
            'provider': record.provider,
            'purpose': purpose,
            'bill_amount': float(record.bill_amount),
            'total': float(record.total_amount),
            'bank': record.bank_display,
            'disclosure_version': DISCLOSURE_VERSION,
        },
    )

    otp_info = send_otp(record, user, ip=ip, device=device)
    return record, otp_info


def send_otp(record: BillPayments, user, ip: str = None, device: str = None) -> dict:
    """Issue (or re-issue) the TRANSACTION OTP for a request awaiting one."""
    if record.status != BillPaymentStatus.AWAITING_OTP:
        raise BillPayError(ErrorCode.CONFLICT, 'This payment no longer needs an OTP.',
                           status=409)
    _expire_if_stale(record)
    try:
        return otp.issue(
            user.phone, purpose=OTPPurpose.TRANSACTION, user_id=user.user_id,
            ip=ip, device_uuid=device,
        )
    except otp.OTPError as exc:
        raise BillPayError(exc.code, exc.message, status=429)


def cancel(record: BillPayments) -> BillPayments:
    """Back out before the OTP. Nothing has moved, so nothing needs undoing."""
    if record.status != BillPaymentStatus.AWAITING_OTP:
        raise BillPayError(ErrorCode.CONFLICT,
                           'This payment is already being processed and cannot be cancelled.',
                           status=409)
    record.status = BillPaymentStatus.CANCELLED
    record.failure_reason = 'Cancelled before authentication.'
    db.session.commit()
    return record


def _expire_if_stale(record: BillPayments):
    if (record.status == BillPaymentStatus.AWAITING_OTP
            and utcnow() - record.created_on > REQUEST_TTL):
        record.status = BillPaymentStatus.EXPIRED
        record.failure_reason = 'The request expired before it was authenticated.'
        db.session.commit()
        raise BillPayError(
            'REQUEST_EXPIRED',
            'This request expired. Nothing was charged - please start again.',
            status=410,
        )


# ── Confirm ────────────────────────────────────────────────────────────────

def confirm(record: BillPayments, user, code: str, sandbox_outcome: str = None) -> BillPayments:
    """
    Verify the OTP, draw the credit and dispatch the payout.

    A replay after the OTP has been accepted returns the record as it stands,
    rather than drawing twice: the status is the answer.
    """
    if record.otp_verified_at is not None:
        return record
    if record.status != BillPaymentStatus.AWAITING_OTP:
        raise BillPayError(ErrorCode.CONFLICT, 'This payment can no longer be confirmed.',
                           status=409)
    _expire_if_stale(record)

    try:
        otp.verify(user.phone, code, purpose=OTPPurpose.TRANSACTION)
    except otp.OTPError as exc:
        raise BillPayError(exc.code, exc.message, status=400)

    # Re-check the destination at the moment money moves: an account can lose
    # its verification between the quote and the OTP.
    bank = db.session.get(BankAccounts, record.bank_account_id)
    if bank is None or not bank.is_payout_eligible or bank.user_id != user.user_id:
        return _fail_before_draw(record, ErrorCode.ACCOUNT_NOT_VERIFIED,
                                 'The destination bank account is no longer verified.')

    record.otp_verified_at = utcnow()
    db.session.commit()

    account = credit_engine.account_for(user.user_id)
    if account is None or account.credit_account_id != record.credit_account_id:
        return _fail_before_draw(record, 'NO_CREDIT_LINE',
                                 'Your credit line is no longer available.')

    try:
        draw, master = credit_engine.draw_for_bill_pay(
            account=account,
            bill_amount=record.bill_amount,
            fee=record.fee_amount,
            gst=record.gst_amount,
            merchant_category=_MERCHANT_CATEGORY.get(record.category, MerchantCategory.OTHER),
            description=(
                f'{record.category_label} · {record.provider} · '
                f'{record.bill_reference_number} · {record.reference}'
            ),
            bank_ref=record.bank_display,
            idempotency_key=record.idempotency_key,
        )
    except credit_engine.DuplicateSpend as exc:
        # The draw landed on an earlier attempt that did not get to save its
        # link. Adopt it rather than draw again.
        draw = exc.transaction
        master = MasterTransactions.query.filter_by(
            transaction_id=draw.transaction_id,
        ).first()
    except credit_engine.CreditError as exc:
        return _fail_before_draw(record, exc.code, exc.message)

    record.transaction_id = draw.transaction_id
    record.credit_transaction_id = draw.credit_transaction_id
    record.available_after = draw.available_after
    record.status = BillPaymentStatus.PROCESSING
    db.session.commit()

    return _dispatch(record, bank, master, sandbox_outcome)


def _fail_before_draw(record: BillPayments, code: str, reason: str) -> BillPayments:
    """Refused before any credit moved. Recorded, because the holder saw it."""
    record.status = BillPaymentStatus.FAILED
    record.failure_code = (code or 'FAILED')[:50]
    record.failure_reason = reason[:500]
    record.completed_at = utcnow()
    db.session.commit()
    audit.record(
        action='BILL_PAY_REFUSED', entity_type='BillPayments',
        entity_id=record.bill_payment_id, actor_user_id=record.user_id,
        after={'code': record.failure_code, 'reason': record.failure_reason},
    )
    return record


def _dispatch(record: BillPayments, bank: BankAccounts, master, sandbox_outcome) -> BillPayments:
    outcome = 'SUCCESS'
    if sandbox_outcome and credit_engine.simulator_allowed():
        outcome = sandbox_outcome

    try:
        account_number = decrypt(bank.account_number_enc)
    except Exception:     # noqa: BLE001 - a key problem must still restore credit
        current_app.logger.exception('[bill_pay] could not decrypt destination account')
        return _restore(record, 'PAYOUT_SETUP_FAILED',
                        'We could not reach your bank. Your credit has been restored.',
                        returned=False)

    result = adapters.dispatch_payout(
        reference=record.reference,
        account_number=account_number,
        ifsc=bank.ifsc_code,
        beneficiary_name=bank.verified_cbs_name or bank.account_holder_name or '',
        amount=record.bill_amount,
        outcome=outcome,
    )
    record.payout_provider = adapters.payout_provider()
    record.payout_dispatched_at = utcnow()
    record.payout_reference = result.get('payout_reference')

    if not result['ok']:
        db.session.commit()
        return _restore(record, result.get('code') or 'PAYOUT_FAILED',
                        result.get('error') or 'The payout could not be completed.',
                        returned=False)

    # Accepted by the rail: the bill amount has left for the partner.
    if master is not None:
        ledger_engine.post_entries(
            master,
            ledger_engine.entries_for_bill_pay_payout(record.bill_amount, record.bank_display),
            commit=False,
        )

    if result['status'] == 'SUCCESS':
        _mark_succeeded(record, master, result.get('utr'))
    else:
        record.status = BillPaymentStatus.PENDING
        db.session.commit()
    return record


def _mark_succeeded(record: BillPayments, master, utr: str):
    record.status = BillPaymentStatus.SUCCEEDED
    record.bank_utr = utr
    record.completed_at = utcnow()
    if master is not None and master.status not in TransactionStatus.TERMINAL:
        ledger_engine.transition(
            master, TransactionStatus.SUCCEEDED,
            bank_rrn_utr=utr, gateway_ref_no=record.payout_reference, commit=False,
        )
    db.session.commit()
    audit.record(
        action='BILL_PAY_SUCCEEDED', entity_type='BillPayments',
        entity_id=record.bill_payment_id, actor_user_id=record.user_id,
        after={'utr': utr, 'amount': float(record.bill_amount)},
    )


def _restore(record: BillPayments, code: str, reason: str, *, returned: bool) -> BillPayments:
    """The payout did not stand: give the whole draw back and say why."""
    draw = (
        db.session.get(CreditTransactions, record.credit_transaction_id)
        if record.credit_transaction_id else None
    )
    if draw is not None:
        restored = credit_engine.restore_bill_pay(
            draw=draw, reason=reason, code=code, returned=returned,
            idempotency_key=f'{record.idempotency_key[:48]}-restore',
        )
        record.restore_credit_transaction_id = restored.credit_transaction_id

    record.status = BillPaymentStatus.REVERSED if returned else BillPaymentStatus.FAILED
    record.failure_code = (code or 'FAILED')[:50]
    record.failure_reason = reason[:500]
    record.completed_at = utcnow()
    db.session.commit()

    audit.record(
        action='BILL_PAY_REVERSED' if returned else 'BILL_PAY_FAILED',
        entity_type='BillPayments', entity_id=record.bill_payment_id,
        actor_user_id=record.user_id,
        after={'code': record.failure_code, 'reason': reason,
               'credit_restored': float(record.total_amount)},
    )
    return record


# ── Status ─────────────────────────────────────────────────────────────────

def refresh(record: BillPayments) -> BillPayments:
    """
    Bring a request up to date with the rail.

    In flight: settle it if the rail has an answer. Recently completed: check
    whether the bank has returned it. Anything else is final and left alone.
    """
    if record.status == BillPaymentStatus.AWAITING_OTP:
        try:
            _expire_if_stale(record)
        except BillPayError:
            pass
        return record

    watching_return = (
        record.status == BillPaymentStatus.SUCCEEDED
        and record.completed_at is not None
        and utcnow() - record.completed_at < RETURN_WINDOW
    )
    if record.status not in BillPaymentStatus.IN_FLIGHT and not watching_return:
        return record
    if not record.payout_reference:
        return record

    status = adapters.get_payout_status(record.payout_reference)
    if not status.get('ok'):
        return record

    master = (
        MasterTransactions.query.filter_by(transaction_id=record.transaction_id).first()
        if record.transaction_id else None
    )

    if status['status'] == 'SUCCESS' and record.status in BillPaymentStatus.IN_FLIGHT:
        _mark_succeeded(record, master, status.get('utr'))
    elif status['status'] == 'FAILED' and record.status in BillPaymentStatus.IN_FLIGHT:
        _restore(record, 'PAYOUT_FAILED', status.get('reason') or 'The payout failed.',
                 returned=False)
    elif status['status'] == 'REVERSED':
        _restore(record, 'PAYOUT_RETURNED',
                 status.get('reason') or 'The bank returned the payment.', returned=True)
    return record


def poll(limit: int = 100) -> dict:
    """Scheduler entry point: expire stale requests and settle in-flight ones."""
    cutoff = utcnow() - REQUEST_TTL
    expired = BillPayments.query.filter(
        BillPayments.status == BillPaymentStatus.AWAITING_OTP,
        BillPayments.created_on < cutoff,
    ).update({'status': BillPaymentStatus.EXPIRED,
              'failure_reason': 'The request expired before it was authenticated.'},
             synchronize_session=False)
    db.session.commit()

    return_cutoff = utcnow() - RETURN_WINDOW
    rows = BillPayments.query.filter(
        db.or_(
            BillPayments.status.in_(BillPaymentStatus.IN_FLIGHT),
            db.and_(BillPayments.status == BillPaymentStatus.SUCCEEDED,
                    BillPayments.completed_at >= return_cutoff),
        )
    ).order_by(BillPayments.created_on.asc()).limit(limit).all()

    changed = 0
    for row in rows:
        before = row.status
        try:
            refresh(row)
        except Exception as exc:    # noqa: BLE001 - one bad row must not stop the sweep
            db.session.rollback()
            current_app.logger.exception(f'[bill_pay] refresh {row.reference} failed: {exc}')
            continue
        if row.status != before:
            changed += 1
    return {'expired': expired, 'checked': len(rows), 'changed': changed}


# ── History ────────────────────────────────────────────────────────────────

def summaries_for(transaction_ids) -> dict:
    """
    {master transaction_id: what History shows about its Pay Bills request}.

    One query for a page of rows. History and the dashboard read the ledger
    row for the money and this for the words - "Electricity Bill", the
    request's own status and its reference.
    """
    ids = [t for t in set(transaction_ids or []) if t]
    if not ids:
        return {}
    rows = BillPayments.query.filter(BillPayments.transaction_id.in_(ids)).all()
    return {
        row.transaction_id: {
            'bill_payment_id': row.bill_payment_id,
            'reference': row.reference,
            'title': f'{row.category_label} Bill' if row.category != BillCategory.OTHER
                     else f'{row.provider} Bill',
            'category': row.category,
            'bill_amount': float(row.bill_amount),
            'status': row.status,
        }
        for row in rows
    }
