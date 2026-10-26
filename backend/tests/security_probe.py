"""
Security and robustness probe, against a running server.

Not a feature walk - those live in the other suites. This sweeps every route
the app registers and asks the questions a reviewer would:

  [1] Unauthenticated   every non-public route refuses a request with no token
  [2] Crash fuzz        no route answers 5xx to empty, malformed or wrong-type
                        input, as a member or as an admin
  [3] Cross-user        a member asking for another account's records by id
                        (cards, tickets, payments, statements, ...) gets 404
                        or 403 - never the record
  [4] Tokens            expired, forged and refresh-as-access tokens refused;
                        logout and "sign out everywhere" end the session
  [5] OTP               an expired or wrong OTP cannot sign in or reset an MPIN
  [6] Verified data     a linked card's CashU-set figures cannot be changed
                        from the client; a manual card cannot be marked
                        bank-verified
  [7] Audit hygiene     no PAN, full card number, MPIN or OTP in audit rows

Destructive routes (account erasure, sign-out-everywhere, MPIN change) are left
out of the fuzz and exercised deliberately in [4].

    python app.py                     # in one terminal
    python tests/security_probe.py    # in another
"""

import json
import os
import re
import sys
import uuid
from datetime import timedelta

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

from credit_lifecycle import BASE, data_of, make_user, post  # noqa: E402

PASS, FAIL = [], []
TIMEOUT = 30


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def clear_throttles():
    from app import app
    from portal import db
    from portal.models.rate_limit_counters import RateLimitCounters
    with app.app_context():
        RateLimitCounters.query.delete()
        db.session.commit()


def call(method, path, token=None, body=None, raw=None, headers=None):
    h = {'X-Device-UUID': 'credit-flow'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    if headers:
        h.update(headers)
    url = path if path.startswith('http') else f'{BASE}{path}'
    if raw is not None:
        h['Content-Type'] = 'application/json'
        return requests.request(method, url, data=raw, headers=h, timeout=TIMEOUT)
    return requests.request(method, url, json=body, headers=h, timeout=TIMEOUT)


# Routes that need no token by design.
PUBLIC = {
    '/v1/', '/v1/doc/', '/v1/swagger.json',
    '/v1/authentication/otp/send', '/v1/authentication/otp/verify',
    '/v1/authentication/mpin/verify', '/v1/authentication/refresh',
    '/v1/authentication/mpin/reset/request', '/v1/authentication/mpin/reset/confirm',
    '/v1/authentication/email/verify',
}
# Signed by the provider instead of a token.
WEBHOOK = re.compile(r'^/v1/webhooks/')

# Never fuzzed: they end the session or change credentials, and are tested on
# purpose in [4] instead.
DESTRUCTIVE = {
    ('POST', '/v1/users/me/erasure'),
    ('POST', '/v1/authentication/logout'),
    ('DELETE', '/v1/authentication/sessions'),
    ('POST', '/v1/authentication/mpin/set'),
    ('POST', '/v1/authentication/refresh'),
}

BODIES = [
    ('no body', None, None),
    ('malformed JSON', None, '{"broken": '),
    ('empty object', {}, None),
    ('wrong types', {
        'amount': 'abc', 'phone': ['x'], 'otp': {'a': 1}, 'mpin': 12.5,
        'consent': 'maybe', 'page': 'x', 'status': {'$ne': 1}, 'reason': None,
        'last4': 12345, 'credit_limit': '-1e9', 'role': 'L3_SUPER_ADMIN',
        'issuer_bank': '<script>x</script>', 'message': 'x' * 20000,
    }, None),
]


def routes():
    """Every /v1 route with its methods, ids filled with a random uuid."""
    from app import app
    seen = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/v1'):
            continue
        path = re.sub(r'<[^>]+>', str(uuid.uuid4()), rule.rule)
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            seen.append((method, rule.rule, path))
    return sorted(set(seen))


def main():
    clear_throttles()
    print('\n[0] Accounts')
    phone_a, token_a = make_user('Probe Owner')
    phone_b, token_b = make_user('Probe Stranger')
    admin_login = post('/authentication/mpin/verify', {
        'phone': os.getenv('ADMIN_SEED_PHONE'), 'mpin': os.getenv('ADMIN_SEED_MPIN')})
    admin = data_of(admin_login).get('access_token')
    if not check('member A, member B and the admin are signed in',
                 token_a and token_b and admin, admin_login.text[:120]):
        return 1

    all_routes = routes()
    print(f'  ({len(all_routes)} method/route pairs registered)')

    # ── [1] ─────────────────────────────────────────────────────────────
    print('\n[1] Every non-public route refuses an anonymous request')
    leaks, crashes = [], []
    for method, rule, path in all_routes:
        if rule in PUBLIC or WEBHOOK.match(rule):
            continue
        r = call(method, path)
        if r.status_code < 400:
            leaks.append(f'{method} {rule} -> {r.status_code}')
        if r.status_code >= 500:
            crashes.append(f'{method} {rule} -> {r.status_code}')
    check('no protected route answers without a token', not leaks, '; '.join(leaks[:10]))
    check('no protected route crashes without a token', not crashes, '; '.join(crashes[:10]))

    # ── [2] ─────────────────────────────────────────────────────────────
    print('\n[2] No route crashes on bad input')
    for who, token in (('member', token_b), ('admin', admin)):
        crashes = []
        for method, rule, path in all_routes:
            if (method, rule) in DESTRUCTIVE or rule in ('/v1/doc/', '/v1/swagger.json'):
                continue
            queries = ['', '?page=abc&per_page=-5&status=%00&q=%27%22']
            for label, body, raw in BODIES:
                for query in (queries if method == 'GET' else ['']):
                    if method == 'GET' and label != 'no body':
                        continue
                    clear_throttles() if len(crashes) > 50 else None
                    r = call(method, path + query, token=token, body=body, raw=raw)
                    if r.status_code >= 500:
                        crashes.append(f'{method} {rule}{query} [{label}] -> {r.status_code}')
        check(f'as {who}: no 5xx across every route and bad body', not crashes,
              '\n      ' + '\n      '.join(crashes[:25]))

    # ── [3] ─────────────────────────────────────────────────────────────
    print('\n[3] Another account\'s records stay private')
    from app import app
    from portal.models.users import Users
    with app.app_context():
        b_id = Users.query.filter_by(phone=phone_b).first().user_id
        targets = foreign_records(b_id)
    for template, record_id, label in targets:
        r = call('GET', template.format(id=record_id), token=token_b)
        check(f'{label}: {r.status_code}', r.status_code in (403, 404),
              r.text[:160])

    # Writes against another person's records.
    with app.app_context():
        writes = foreign_writes(b_id)
    for method, template, record_id, body, label in writes:
        r = call(method, template.format(id=record_id), token=token_b, body=body)
        check(f'{label}: {r.status_code}', r.status_code in (403, 404, 405, 409), r.text[:160])

    # ── [4] ─────────────────────────────────────────────────────────────
    print('\n[4] Tokens and sessions')
    from flask_jwt_extended import create_access_token
    with app.app_context():
        user = Users.query.filter_by(phone=phone_b).first()
        expired = create_access_token(identity=str(user.user_id),
                                      expires_delta=timedelta(seconds=-60),
                                      additional_claims={'role': 'NORMAL_USER'})
    r = call('GET', '/users/me', token=expired)
    check('an expired token is refused with 401 and says why',
          r.status_code == 401 and 'expired' in r.text.lower(), r.text[:160])
    head, payload, _sig = token_b.split('.')
    r = call('GET', '/users/me', token=f'{head}.{payload}.forgedsignature')
    check('a forged signature is refused', r.status_code in (401, 422), r.text[:160])
    elevated = json.loads(_b64(payload))
    elevated['role'] = 'L3_SUPER_ADMIN'
    tampered = f'{head}.{_b64e(json.dumps(elevated))}.{_sig}'
    r = call('GET', '/admin/dashboard', token=tampered)
    check('editing the role inside a token does not make an admin', r.status_code in (401, 422),
          r.text[:160])
    r = call('GET', '/users/me', token='not-a-jwt')
    check('garbage in the Authorization header is refused', r.status_code in (401, 422))

    login = data_of(post('/authentication/mpin/verify', {'phone': phone_a, 'mpin': '246813'}))
    access, refresh = login.get('access_token'), login.get('refresh_token')
    r = call('GET', '/users/me', token=refresh)
    check('a refresh token cannot be used as an access token', r.status_code in (401, 422),
          r.text[:120])
    r = call('POST', '/authentication/logout', token=access)
    check('logout succeeds', r.status_code == 200)
    check('after logout the access token is dead', call('GET', '/users/me', token=access).status_code == 401)
    check('after logout the refresh token is dead',
          call('POST', '/authentication/refresh', token=refresh).status_code == 401)

    other = data_of(post('/authentication/mpin/verify', {'phone': phone_a, 'mpin': '246813'}))
    third = data_of(post('/authentication/mpin/verify', {'phone': phone_a, 'mpin': '246813'}))
    r = call('DELETE', '/authentication/sessions', token=third.get('access_token'))
    check('"sign out everywhere" succeeds', r.status_code == 200)
    check('and ends the other device\'s session too',
          call('GET', '/users/me', token=other.get('access_token')).status_code == 401)

    clear_throttles()
    r = post('/authentication/mpin/verify', {'phone': phone_a})
    check('sign-in with a missing MPIN is a 400, not a crash', r.status_code == 400, r.text[:120])
    r = post('/authentication/otp/send', {})
    check('OTP request with no phone is a 400', r.status_code == 400)
    r = post('/authentication/otp/send', {'phone': '12345'})
    check('OTP request with an invalid phone is a 400', r.status_code == 400)

    # ── [5] ─────────────────────────────────────────────────────────────
    print('\n[5] OTPs')
    clear_throttles()
    sent = data_of(post('/authentication/mpin/reset/request', {'phone': phone_a}))
    code = sent.get('debug_otp')
    with app.app_context():
        from portal import db
        from portal.models.base import utcnow
        from portal.models.otp_verifications import OTPVerifications
        row = OTPVerifications.query.filter_by(phone=phone_a).order_by(
            OTPVerifications.created_on.desc()).first()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
    r = post('/authentication/mpin/reset/confirm', {'phone': phone_a, 'otp': code, 'mpin': '582914'})
    check('an expired reset OTP cannot reset the MPIN', r.status_code == 400, r.text[:160])
    check('and the old MPIN still works',
          post('/authentication/mpin/verify', {'phone': phone_a, 'mpin': '246813'}).status_code == 200)
    clear_throttles()
    sent = data_of(post('/authentication/otp/send', {'phone': phone_a}))
    wrong = '000000' if sent.get('debug_otp') != '000000' else '111111'
    r = post('/authentication/otp/verify', {'phone': phone_a, 'otp': wrong})
    check('a wrong sign-in OTP is refused', r.status_code == 400 and 'access_token' not in r.text)
    r = post('/authentication/mpin/reset/confirm', {'phone': phone_a, 'otp': sent.get('debug_otp'),
                                                   'mpin': '582914'})
    check('a sign-in OTP cannot be used to reset an MPIN', r.status_code == 400, r.text[:160])

    # ── [6] ─────────────────────────────────────────────────────────────
    print('\n[6] Figures the client must not be able to change')
    clear_throttles()
    token_a = data_of(post('/authentication/mpin/verify', {'phone': phone_a, 'mpin': '246813'})).get('access_token')
    with app.app_context():
        from portal.models.cards import Cards, CardStatus
        tokenised = Cards.query.filter(Cards.status != CardStatus.DELETED).first()
        owner_phone = Users.query.filter_by(user_id=tokenised.user_id).first().phone if tokenised else None
    if tokenised:
        from portal.helpers.jwt import issue_tokens
        with app.app_context():
            owner = Users.query.filter_by(phone=owner_phone).first()
            tokens = issue_tokens(owner, device_uuid='credit-flow')
            owner_token = tokens['access_token'] if isinstance(tokens, dict) else tokens[0]
            before = (tokenised.card_limit, tokenised.available_limit, tokenised.outstanding_amount)
        r = call('PATCH', f'/cards/{tokenised.card_id}', token=owner_token,
                 body={'card_limit': 9999999, 'available_limit': 9999999, 'outstanding_amount': 0})
        check('a linked card cannot be edited by its own holder', r.status_code == 403, r.text[:120])
        r = call('PUT', f'/cards/{tokenised.card_id}/theme', token=owner_token,
                 body={'theme': 'PURPLE', 'card_limit': 9999999})
        with app.app_context():
            after = Cards.query.get(tokenised.card_id)
            unchanged = (after.card_limit, after.available_limit, after.outstanding_amount) == before
            after.card_theme = None
            from portal import db
            db.session.commit()
        check('changing a theme cannot carry a limit change with it', unchanged)

    r = call('POST', '/cards/manual', token=token_a, body={
        'issuer_bank': 'Axis Bank', 'last4': '9012', 'credit_limit': '50000',
        'bank_verified': True, 'data_source': 'PROVIDER_VERIFIED'})
    card = data_of(r)
    check('a manual card cannot be created as bank-verified',
          r.status_code == 201 and card.get('bank_verified') is False
          and card.get('data_source') == 'USER_ENTERED', r.text[:200])
    r = call('PATCH', f'/cards/manual/{card.get("manual_card_id")}', token=token_a,
             body={'bank_verified': True, 'data_source': 'PROVIDER_VERIFIED', 'status': 'ACTIVE',
                   'user_id': b_id})
    edited = data_of(r)
    check('nor patched into one, nor moved to another account',
          edited.get('bank_verified') is False and edited.get('data_source') == 'USER_ENTERED',
          r.text[:200])
    with app.app_context():
        from portal.models.manual_cards import ManualCards
        row = ManualCards.query.get(card.get('manual_card_id'))
        check('the row still belongs to its creator', row and row.user_id != b_id)

    # ── [7] ─────────────────────────────────────────────────────────────
    print('\n[7] Audit trail hygiene')
    with app.app_context():
        from portal.models.audit_logs import AuditLogs
        pan = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')
        card_number = re.compile(r'\b\d{13,19}\b')
        secret_key = re.compile(r'"(mpin|otp|password|cvv|pin)"\s*:\s*"[^"*]+"', re.I)
        hits = []
        for row in AuditLogs.query.order_by(AuditLogs.created_on.desc()).limit(5000):
            blob = ' '.join(filter(None, [row.before_state, row.after_state, row.notes]))
            for name, rx in (('PAN', pan), ('card number', card_number), ('secret', secret_key)):
                if rx.search(blob):
                    hits.append(f'{row.action}: {name}')
        check('no PAN, card number, MPIN or OTP in the last 5,000 audit rows', not hits,
              '; '.join(sorted(set(hits))[:10]))

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    return 1 if FAIL else 0


def _b64(part):
    import base64
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)).decode()


def _b64e(text):
    import base64
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


def foreign_records(b_id):
    """(url template, id, label) for one record of each kind B does not own."""
    from portal.models.bank_accounts import BankAccounts
    from portal.models.bill_payments import BillPayments
    from portal.models.cards import Cards
    from portal.models.credit_applications import CreditApplications
    from portal.models.credit_statements import CreditStatements
    from portal.models.credit_transactions import CreditTransactions
    from portal.models.emi_obligations import EMIObligations
    from portal.models.emi_payments import EMIPayments
    from portal.models.manual_cards import ManualCards
    from portal.models.master_transactions import MasterTransactions
    from portal.models.qr_payments import QRPayments
    from portal.models.support_messages import SupportTickets

    plan = [
        (Cards, 'card_id', '/cards/{id}', 'another member\'s card'),
        (ManualCards, 'manual_card_id', '/cards/manual/{id}', 'another member\'s manual card'),
        (SupportTickets, 'ticket_id', '/support/tickets/{id}', 'another member\'s support ticket'),
        (CreditApplications, 'application_id', '/credit/applications/{id}', 'another member\'s credit application'),
        (CreditTransactions, 'credit_transaction_id', '/credit/transactions/{id}', 'another member\'s credit transaction'),
        (CreditStatements, 'statement_id', '/credit/statements/{id}', 'another member\'s statement'),
        (BillPayments, 'bill_payment_id', '/bill-payments/{id}', 'another member\'s bill payment'),
        (BankAccounts, 'bank_account_id', '/bank-accounts/{id}', 'another member\'s bank account'),
        (EMIObligations, 'emi_id', '/emi/{id}', 'another member\'s EMI'),
        (EMIPayments, 'payment_id', '/emi-payments/{id}', 'another member\'s EMI payment'),
        (EMIPayments, 'payment_id', '/emi-payments/{id}/receipt', 'another member\'s EMI receipt'),
        (QRPayments, 'qr_payment_id', '/qr-payments/{id}', 'another member\'s QR payment'),
        (MasterTransactions, 'transaction_id', '/transactions/{id}', 'another member\'s transaction'),
    ]
    out = []
    for model, pk, template, label in plan:
        owner_col = getattr(model, 'user_id', None)
        if owner_col is None:
            continue
        row = model.query.filter(owner_col != b_id).first()
        if row is not None:
            out.append((template, getattr(row, pk), label))
        else:
            print(f'  (no {model.__tablename__} rows to test with)')
    return out


def foreign_writes(b_id):
    from portal.models.manual_cards import ManualCards, ManualCardStatus
    from portal.models.support_messages import SupportTickets
    from portal.models.credit_transactions import CreditTransactions
    from portal.models.bill_payments import BillPayments
    out = []
    card = ManualCards.query.filter(ManualCards.user_id != b_id,
                                    ManualCards.status == ManualCardStatus.ACTIVE).first()
    if card:
        out += [
            ('PATCH', '/cards/manual/{id}', card.manual_card_id, {'credit_limit': '1'}, 'edit another member\'s manual card'),
            ('DELETE', '/cards/manual/{id}', card.manual_card_id, None, 'remove another member\'s manual card'),
        ]
    ticket = SupportTickets.query.filter(SupportTickets.user_id != b_id).first()
    if ticket:
        out.append(('POST', '/support/tickets/{id}/reply', ticket.ticket_id,
                    {'message': 'not mine'}, 'reply on another member\'s ticket'))
    txn = CreditTransactions.query.filter(CreditTransactions.user_id != b_id).first()
    if txn:
        out.append(('POST', '/credit/payments/{id}/cancel', txn.credit_transaction_id, None,
                    'cancel another member\'s credit payment'))
    bill = BillPayments.query.filter(BillPayments.user_id != b_id).first()
    if bill:
        out.append(('POST', '/bill-payments/{id}/cancel', bill.bill_payment_id, None,
                    'cancel another member\'s bill payment'))
    return out


if __name__ == '__main__':
    sys.exit(main())
