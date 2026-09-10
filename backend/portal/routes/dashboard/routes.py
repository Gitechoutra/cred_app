"""
Home dashboard telemetry (PRD FR-002, section 7).

One aggregated payload rather than six round trips, because the PRD budgets the
whole dashboard render at under 400ms and a mobile client on Indian 4G cannot
afford the latency of fanning out.
"""

from datetime import timedelta

from flask_jwt_extended import jwt_required
from flask_restx import Resource

from portal import db
from portal.helpers.helpers import iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.models.auto_pay_mandates import AutoPayMandates, MandateStatus
from portal.models.bank_accounts import BankAccounts, PennyDropStatus
from portal.models.base import utcnow
from portal.models.cards import Cards, CardStatus
from portal.models.emi_obligations import EMIObligations, EMIPaymentStatus
from portal.models.master_transactions import MasterTransactions
from portal.models.notifications import Notifications
from portal.models.transfers import Transfers

from . import ns


def _utilization_badge(percentage):
    """
    Map credit utilization onto a label and tone.

    The colour encodes advice, not judgement: above 80% is flagged because it
    materially hurts a credit score, not to shame the user.
    """
    if percentage is None:
        return {'label': 'Not tracked', 'tone': 'neutral'}
    if percentage <= 30:
        return {'label': 'Optimal', 'tone': 'good'}
    if percentage <= 60:
        return {'label': 'Moderate', 'tone': 'neutral'}
    if percentage <= 80:
        return {'label': 'High', 'tone': 'warn'}
    return {'label': 'Very High', 'tone': 'alert'}


@ns.route('')
class Dashboard(Resource):
    @ns.doc('get_dashboard', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        Aggregate view of everything the user owes (PRD FR-002).

        Returns total limit, available limit, outstanding, utilization, the
        nearest due item across cards and EMIs, and the recent activity feed.
        """
        user = current_user()
        today = utcnow().date()
        horizon = today + timedelta(days=30)

        cards = Cards.query.filter(
            Cards.user_id == user.user_id,
            Cards.status != CardStatus.DELETED,
        ).order_by(Cards.created_on.asc()).all()

        obligations = EMIObligations.query.filter(
            EMIObligations.user_id == user.user_id,
            EMIObligations.is_active.is_(True),
        ).order_by(EMIObligations.next_due_date.asc()).all()

        total_limit = sum(float(c.card_limit or 0) for c in cards)
        total_outstanding = sum(float(c.outstanding_amount or 0) for c in cards)
        total_available = sum(
            float(c.available_limit if c.available_limit is not None
                  else (c.card_limit or 0) - (c.outstanding_amount or 0))
            for c in cards
        )
        emi_outstanding = sum(float(e.outstanding_bal or 0) for e in obligations)
        monthly_emi = sum(float(e.emi_amount or 0) for e in obligations)

        utilization = (
            round(total_outstanding / total_limit * 100, 2)
            if total_limit > 0 else None
        )

        # -- Nearest due across both card bills and EMIs -------------------
        due_items = []

        for card in cards:
            if card.next_due_date and today <= card.next_due_date <= horizon:
                due_items.append({
                    'type': 'CARD',
                    'id': card.card_id,
                    'title': f'{card.card_issuer_bank} {card.masked_pan}',
                    'subtitle': card.nickname or card.card_network,
                    'amount': to_float(card.current_due_amount),
                    'minimum_due': to_float(card.minimum_due_amount),
                    'due_date': iso(card.next_due_date),
                    'days_remaining': (card.next_due_date - today).days,
                    'is_overdue': False,
                    'auto_pay': False,
                })

        for emi in obligations:
            if emi.next_due_date and emi.next_due_date <= horizon:
                due_items.append({
                    'type': 'EMI',
                    'id': emi.emi_id,
                    'title': emi.provider_name,
                    'subtitle': emi.nickname or emi.masked_loan_account(),
                    'amount': to_float(emi.emi_amount),
                    'minimum_due': None,
                    'due_date': iso(emi.next_due_date),
                    'days_remaining': (emi.next_due_date - today).days,
                    'is_overdue': emi.payment_status == EMIPaymentStatus.OVERDUE,
                    'auto_pay': emi.auto_pay_status == 'ACTIVE',
                })

        # Overdue first, then soonest.
        due_items.sort(key=lambda d: (not d['is_overdue'], d['days_remaining']))

        # -- Recent activity ------------------------------------------------
        recent = MasterTransactions.query.filter_by(
            user_id=user.user_id
        ).order_by(MasterTransactions.created_on.desc()).limit(5).all()

        verified_accounts = BankAccounts.query.filter_by(
            user_id=user.user_id,
            penny_drop_status=PennyDropStatus.VERIFIED,
            deleted_at=None,
        ).count()

        unread = Notifications.query.filter_by(
            user_id=user.user_id, is_read=False
        ).count()

        active_mandates = AutoPayMandates.query.filter_by(
            user_id=user.user_id, status=MandateStatus.ACTIVE
        ).count()

        return success({
            'greeting_name': (user.full_name or '').split(' ')[0] or 'there',
            'kyc_tier': user.kyc_tier,
            'kyc_status': (
                user.kyc_verification.kyc_status if user.kyc_verification
                else 'NOT_STARTED'
            ),
            'unread_notifications': unread,

            'summary': {
                'total_credit_limit': round(total_limit, 2),
                'total_available_credit': round(max(0.0, total_available), 2),
                'total_outstanding_amount': round(total_outstanding, 2),
                'credit_utilization_percentage': utilization,
                'utilization_badge': _utilization_badge(utilization),
                'emi_outstanding': round(emi_outstanding, 2),
                'monthly_emi_commitment': round(monthly_emi, 2),
                'total_debt': round(total_outstanding + emi_outstanding, 2),
            },

            'next_due_item': due_items[0] if due_items else None,
            'upcoming_dues': due_items[:5],

            'cards': [{
                'card_id': c.card_id,
                'masked_pan': c.masked_pan,
                'issuer_bank': c.card_issuer_bank,
                'network': c.card_network,
                'nickname': c.nickname,
                'brand_color': c.brand_color,
                'card_limit': to_float(c.card_limit),
                'available_limit': to_float(c.available_limit),
                'outstanding_amount': to_float(c.outstanding_amount),
                'utilization_percentage': c.utilization_percentage,
                'current_due_amount': to_float(c.current_due_amount),
                'next_due_date': iso(c.next_due_date),
                'status': c.status,
            } for c in cards],

            'emi_obligations': [{
                'emi_id': e.emi_id,
                'provider_name': e.provider_name,
                'masked_loan_account': e.masked_loan_account(),
                'nickname': e.nickname,
                'emi_amount': to_float(e.emi_amount),
                'next_due_date': iso(e.next_due_date),
                'tenure_remaining': e.tenure_remaining,
                'total_tenure': e.total_tenure,
                'outstanding_bal': to_float(e.outstanding_bal),
                'auto_pay_status': e.auto_pay_status,
                'payment_status': e.payment_status,
                'loan_type': e.loan_type,
            } for e in obligations],

            'recent_transactions': [{
                'transaction_id': t.transaction_id,
                'type': t.transaction_type,
                'amount': to_float(t.gross_amount),
                'status': t.status,
                'source': t.source_masked_ref,
                'destination': t.dest_masked_ref,
                'created_on': iso(t.created_on),
                'utr': t.bank_rrn_utr,
            } for t in recent],

            'quick_actions': {
                'can_transfer': bool(cards) and verified_accounts > 0,
                'can_pay_emi': bool(obligations),
                'can_add_card': True,
                'can_add_emi': True,
                'needs_bank_account': verified_accounts == 0,
                'needs_kyc': user.kyc_tier == 'NONE',
            },

            'counts': {
                'cards': len(cards),
                'emi_obligations': len(obligations),
                'verified_bank_accounts': verified_accounts,
                'active_mandates': active_mandates,
            },
        })


@ns.route('/activity')
class RecentActivity(Resource):
    @ns.doc('get_activity', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Recent activity feed for the home screen."""
        user = current_user()

        transactions = MasterTransactions.query.filter_by(
            user_id=user.user_id
        ).order_by(MasterTransactions.created_on.desc()).limit(20).all()

        return success([{
            'transaction_id': t.transaction_id,
            'type': t.transaction_type,
            'amount': to_float(t.gross_amount),
            'net_amount': to_float(t.net_amount),
            'fee': to_float(t.fee_amount),
            'status': t.status,
            'source': t.source_masked_ref,
            'destination': t.dest_masked_ref,
            'utr': t.bank_rrn_utr,
            'created_on': iso(t.created_on),
        } for t in transactions])
