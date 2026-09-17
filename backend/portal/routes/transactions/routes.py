"""
Transaction history and ledger view (PRD FR-010).

Read-only by construction: nothing in this module writes. Financial rows are
append-only, and corrections are compensating entries posted by the engines.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers.helpers import (
    ErrorCode, failure, iso, paginated, success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import validate_date, validate_pagination
from portal.models.double_entry_ledger import DoubleEntryLedger
from portal.models.master_transactions import (
    MasterTransactions, TransactionStatus, TransactionType,
)

from . import ns

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('type', type=str, required=False, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')
list_parser.add_argument('from_date', type=str, required=False, location='args')
list_parser.add_argument('to_date', type=str, required=False, location='args')
list_parser.add_argument('search', type=str, required=False, location='args')


def transaction_dict(txn: MasterTransactions, detailed: bool = False) -> dict:
    data = {
        'transaction_id': txn.transaction_id,
        'type': txn.transaction_type,
        'gross_amount': to_float(txn.gross_amount),
        'net_amount': to_float(txn.net_amount),
        'fee_amount': to_float(txn.fee_amount),
        'tax_amount': to_float(txn.tax_amount),
        'currency': txn.currency,
        'source': txn.source_masked_ref,
        'source_type': txn.source_type,
        'destination': txn.dest_masked_ref,
        'dest_type': txn.dest_type,
        'status': txn.status,
        'utr': txn.bank_rrn_utr,
        'gateway_reference': txn.gateway_ref_no,
        'failure_code': txn.failure_code,
        'failure_reason': txn.failure_reason,
        'created_on': iso(txn.created_on),
    }

    if detailed:
        data['gateway_provider'] = txn.gateway_provider
        data['recon_status'] = txn.recon_status
        data['reverses_transaction_id'] = txn.reverses_transaction_id

        # Attach linked transfer balance audit details if available
        from portal.models.transfers import Transfers
        t = Transfers.query.filter_by(transaction_id=txn.transaction_id).first()
        if t:
            data['source_opening_balance'] = to_float(t.source_opening_balance)
            data['source_closing_balance'] = to_float(t.source_closing_balance)
            data['destination_opening_balance'] = to_float(t.destination_opening_balance)
            data['destination_closing_balance'] = to_float(t.destination_closing_balance)
            if t.bank_account:
                data['destination_bank_name'] = t.bank_account.bank_name
                data['destination_ifsc'] = t.bank_account.ifsc_code

        # The journal entries behind this transaction. Surfaced so a support
        # agent can see exactly how the money was accounted for without
        # database access (PRD 15: zero-DB even for L3).
        data['ledger_entries'] = [{
            'account_code': entry.account_code,
            'debit': to_float(entry.debit_amount),
            'credit': to_float(entry.credit_amount),
            'narration': entry.narration,
            'entry_timestamp': iso(entry.entry_timestamp),
        } for entry in txn.ledger_entries.order_by(
            DoubleEntryLedger.entry_timestamp.asc()
        ).all()]

    return data


@ns.route('')
class TransactionList(Resource):
    @ns.doc('list_transactions', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        Paginated, filterable transaction history (PRD FR-010).

        Filters: type, status, date range, and a free-text search over the UTR
        and gateway reference - which is how a user actually looks for a
        specific payment.
        """
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = MasterTransactions.query.filter_by(user_id=user.user_id)

        if args.get('type'):
            query = query.filter(MasterTransactions.transaction_type == args['type'])
        if args.get('status'):
            query = query.filter(MasterTransactions.status == args['status'])

        from_date = validate_date(args.get('from_date'), 'from_date')
        to_date = validate_date(args.get('to_date'), 'to_date')
        if from_date:
            query = query.filter(MasterTransactions.created_on >= from_date)
        if to_date:
            from datetime import timedelta
            query = query.filter(
                MasterTransactions.created_on < to_date + timedelta(days=1)
            )

        if args.get('search'):
            term = f"%{args['search'].strip()}%"
            query = query.filter(
                MasterTransactions.bank_rrn_utr.ilike(term)
                | MasterTransactions.gateway_ref_no.ilike(term)
                | MasterTransactions.dest_masked_ref.ilike(term)
            )

        pagination = query.order_by(
            MasterTransactions.created_on.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return paginated(
            [transaction_dict(t) for t in pagination.items],
            page, per_page, pagination.total,
            filters={
                'types': TransactionType.CHOICES,
                'statuses': TransactionStatus.CHOICES,
            },
        )


@ns.route('/<string:transaction_id>')
class TransactionDetail(Resource):
    @ns.doc('get_transaction', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, transaction_id):
        """One transaction with its double-entry journal."""
        user = current_user()

        txn = MasterTransactions.query.filter_by(
            transaction_id=transaction_id, user_id=user.user_id
        ).first()

        if not txn:
            return failure(ErrorCode.NOT_FOUND, 'Transaction not found.', 404)

        return success(transaction_dict(txn, detailed=True))


@ns.route('/summary')
class TransactionSummary(Resource):
    @ns.doc('get_summary', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Lifetime totals for the transactions screen header."""
        from sqlalchemy import func

        from portal import db

        user = current_user()

        rows = db.session.query(
            MasterTransactions.transaction_type,
            func.count(MasterTransactions.transaction_id),
            func.coalesce(func.sum(MasterTransactions.gross_amount), 0),
            func.coalesce(func.sum(MasterTransactions.fee_amount), 0),
        ).filter(
            MasterTransactions.user_id == user.user_id,
            MasterTransactions.status == TransactionStatus.SUCCEEDED,
        ).group_by(MasterTransactions.transaction_type).all()

        by_type = {
            row[0]: {
                'count': row[1],
                'total_amount': float(row[2]),
                'total_fees': float(row[3]),
            }
            for row in rows
        }

        return success({
            'by_type': by_type,
            'total_transacted': sum(v['total_amount'] for v in by_type.values()),
            'total_fees_paid': sum(v['total_fees'] for v in by_type.values()),
            'transaction_count': sum(v['count'] for v in by_type.values()),
        })
