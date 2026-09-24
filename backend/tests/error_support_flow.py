"""
Transaction error capture, the support bot, and admin monitoring.

The assertions that matter are the ones about what is *not* said: that a
declined payment never shows a bare "Payment failed", and that a stored
gateway payload never contains a card number, CVV or token.

    python tests/error_support_flow.py
"""

import json
import os
import random
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from throttle import throttled  # noqa: E402

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 45

PASS, FAIL = [], []
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 200


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    print(f'  [{"PASS" if condition else "FAIL"}] {label}'
          + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def post(path, body=None, token=None, idem=None, form=None, files=None):
    h = {'X-Device-UUID': 'err-flow'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    if idem:
        h['X-Idempotency-Key'] = idem
    if files or form:
        return throttled(lambda: requests.post(
            f'{BASE}{path}', data=form, files=files,
            headers=h, timeout=TIMEOUT))
    return throttled(lambda: requests.post(
        f'{BASE}{path}', json=body or {}, headers=h, timeout=TIMEOUT))


def get(path, token=None):
    h = {'X-Device-UUID': 'err-flow'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    return throttled(lambda: requests.get(
        f'{BASE}{path}', headers=h, timeout=TIMEOUT))


def data_of(r):
    try:
        return r.json().get('data') or {}
    except ValueError:
        return {}


def finish():
    print('\n' + '=' * 64)
    print(f'{len(PASS)} passed, {len(FAIL)} failed')
    for f in FAIL:
        print(f'  FAILED: {f}')
    return 1 if FAIL else 0


def main():
    phone = f'9{random.randint(100000000, 999999999)}'
    print(f'\nError capture and support - phone {phone}\n' + '=' * 64)

    print('\nSetup')
    otp = data_of(post('/authentication/otp/send', {'phone': phone})).get('debug_otp')
    if not check('OTP issued', bool(otp)):
        return finish()
    token = data_of(post('/authentication/otp/verify',
                         {'phone': phone, 'otp': otp})).get('access_token')
    if not check('signed in', bool(token)):
        return finish()

    post('/authentication/register',
         {'full_name': 'Error Tester', 'terms_accepted': True}, token=token)
    post('/authentication/mpin/set', {'mpin': '246813'}, token=token)

    post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F', 'full_name': 'Error Tester',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', PNG, 'image/png')}, token=token)

    admin = post('/authentication/mpin/verify',
                 {'phone': '9999999999', 'mpin': '135790'})
    admin_token = data_of(admin).get('access_token')
    if admin_token:
        queue = get('/admin/kyc/queue', admin_token).json().get('data') or []
        mine = [k for k in queue if (k.get('masked_phone') or '').endswith(phone[-4:])]
        if mine:
            post(f"/admin/kyc/{mine[0]['kyc_id']}/review",
                 {'decision': 'APPROVE', 'tier': 'MINIMUM'}, token=admin_token)
        again = post('/authentication/mpin/verify', {'phone': phone, 'mpin': '246813'})
        if again.status_code == 200:
            token = again.json()['data']['access_token']

    cards = data_of(get('/cards/test-cards', token)).get('cards', [])
    catalogue = {c['scenario']: c for c in cards}
    if not check('test cards available', bool(catalogue)):
        return finish()

    decline = catalogue['DECLINE']
    linked = data_of(post('/cards', {
        'bin': decline['bin'], 'last4': decline['last4'],
        'expiry_month': decline['expiry_month'], 'expiry_year': decline['expiry_year'],
        'cardholder_name': decline['cardholder_name'],
        'issuer_bank': decline['issuer_bank'], 'brand_color': decline['brand_color'],
        'due_day': 10,
    }, token=token))
    if not check('decline card linked', bool(linked.get('card_id'))):
        return finish()

    account = f'5010{random.randint(10000000, 99999999)}'
    bank = data_of(post('/bank-accounts', {
        'account_number': account, 'confirm_account_number': account,
        'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
        'account_holder_name': 'Error Tester', 'is_primary': True,
    }, token=token)).get('bank_account_id')
    if not check('payout account added', bool(bank)):
        return finish()

    # -- Produce a real failure -------------------------------------------
    #
    # This suite needs a payment that genuinely fails, so it can then assert
    # what was recorded about it and what the support bot says. It used to get
    # that from a credit-to-bank transfer charged against the DECLINE test
    # card. That product has been removed, and its replacement - a purchase on
    # an issued credit line - is not built yet.
    #
    # Deliberately left failing rather than skipped. Everything below is real
    # coverage of error capture, sanitisation and the chatbot, and a green run
    # here would claim it while proving nothing.
    print('\nFailure capture')
    check('a failing payment path exists to capture errors from', False,
          'BLOCKED: needs the card purchase flow. Retarget onto it once the '
          'credit-line lifecycle lands, then the 40+ checks below run again.')
    return finish()

    opened = data_of(post('/transfers', {
        'card_id': linked['card_id'], 'bank_account_id': bank, 'amount': 2000,
    }, token=token, idem=f'err-{phone}'))
    if not check('transfer opens', bool(opened.get('transfer_id'))):
        return finish()

    confirmed = data_of(post(f"/transfers/{opened['transfer_id']}/confirm",
                             token=token))
    check('transfer fails as expected', confirmed.get('status') == 'FAILED',
          str(confirmed.get('status')))

    # -- The user-facing explanation --------------------------------------
    print('\nWhat the user is told')
    response = get(f"/support/transaction-error/Transfers/{opened['transfer_id']}",
                   token)
    ctx = data_of(response)

    check('error record is retrievable', response.status_code == 200,
          response.text[:160])
    check('a specific reason is given, not "Payment failed"',
          bool(ctx.get('error_message'))
          and ctx['error_message'].lower().strip() != 'payment failed',
          str(ctx.get('error_message')))
    check('reason names the decline',
          'declin' in (ctx.get('error_message') or '').lower(),
          str(ctx.get('error_message')))
    check('classified by type', ctx.get('error_type') == 'INSTRUMENT',
          str(ctx.get('error_type')))
    check('transaction id attached', bool(ctx.get('transaction_id')))
    check('amount attached', ctx.get('amount') is not None)
    check('actions offered', len(ctx.get('actions') or []) >= 2,
          str(ctx.get('actions')))
    check('marked retryable', ctx.get('is_retryable') is True)

    check('no gateway payload leaked to the user',
          'gateway_response' not in ctx and 'error_reason' not in ctx,
          str(sorted(ctx.keys())))

    # -- The bot ----------------------------------------------------------
    print('\nSupport bot')
    response = post('/support/chat', {
        'reference_type': 'Transfers', 'reference_id': opened['transfer_id'],
    }, token=token)
    chat = data_of(response)

    check('bot opens with the payment', response.status_code == 200,
          response.text[:160])
    opening = ' '.join(m['text'] for m in chat.get('messages', []))
    check('bot states the amount', '2,0' in opening or '2000' in opening, opening[:120])
    check('bot states the reason', 'declin' in opening.lower(), opening[:160])
    check('bot says whether money moved',
          'charg' in opening.lower(), opening[:160])
    check('bot offers follow-ups', len(chat.get('options') or []) >= 2)
    check('context attached without the user typing it',
          chat.get('context', {}).get('transaction_id') == ctx.get('transaction_id'))

    response = post('/support/chat', {
        'reference_type': 'Transfers', 'reference_id': opened['transfer_id'],
        'intent': 'WAS_I_CHARGED',
    }, token=token)
    answer = ' '.join(m['text'] for m in data_of(response).get('messages', []))
    check('answers "was I charged" specifically',
          'charg' in answer.lower(), answer[:140])

    response = post('/support/chat', {
        'reference_type': 'Transfers', 'reference_id': opened['transfer_id'],
        'intent': 'NOT_A_REAL_INTENT',
    }, token=token)
    check('unknown intent refused', response.status_code == 400,
          f'got {response.status_code}')

    # -- Escalation --------------------------------------------------------
    print('\nEscalation')
    response = post('/support/escalate', {
        'reference_type': 'Transfers', 'reference_id': opened['transfer_id'],
        'note': 'Tried twice, same result.',
    }, token=token)
    ticket = data_of(response)
    check('ticket created', response.status_code == 201, response.text[:160])
    check('ticket number issued', bool(ticket.get('ticket_number')))

    if ticket.get('ticket_id'):
        thread = data_of(get(f"/support/tickets/{ticket['ticket_id']}", token))
        body = json.dumps(thread)
        check('transaction details attached automatically',
              ctx['transaction_id'] in body, 'transaction id missing from thread')
        check('failure reason attached automatically',
              'declin' in body.lower(), 'reason missing from thread')

    # -- Admin -------------------------------------------------------------
    print('\nAdmin monitoring')
    if not admin_token:
        check('admin available', False, 'could not sign in')
        return finish()

    response = get('/admin/transaction-errors', admin_token)
    rows = response.json().get('data') or []
    check('admin can list errors', response.status_code == 200, response.text[:160])
    check('the failure appears', len(rows) >= 1, str(len(rows)))

    mine_rows = [r for r in rows if r.get('reference_id') == opened['transfer_id']]
    check('this failure is listed', len(mine_rows) == 1, str(len(mine_rows)))

    if mine_rows:
        row = mine_rows[0]
        check('admin sees the technical reason', 'error_reason' in row)
        check('admin sees the gateway payload', 'gateway_response' in row)

        payload = json.dumps(row)
        for secret in ['cvv', 'card_number', '"pan"', 'password', 'key_secret']:
            check(f'no {secret} in the stored payload',
                  secret not in payload.lower(), 'sensitive key present')
        check('no 16-digit card number in the payload',
              not any(len(tok) >= 13 and tok.isdigit()
                      for tok in payload.replace('"', ' ').split()),
              'digit run that could be a PAN')

        response = post(f"/admin/transaction-errors/{row['error_id']}/resolve",
                        {'notes': 'Customer used another card successfully.'},
                        token=admin_token)
        check('admin can resolve', response.status_code == 200, response.text[:160])
        check('resolution recorded', data_of(response).get('is_resolved') is True)

        response = post(f"/admin/transaction-errors/{row['error_id']}/resolve",
                        {'notes': '   '}, token=admin_token)
        check('empty resolution note refused', response.status_code == 400,
              f'got {response.status_code}')

    response = get('/admin/transaction-errors?error_type=INSTRUMENT', admin_token)
    check('filter by type works', response.status_code == 200)

    response = get(f"/admin/transaction-errors?search={opened['transfer_id']}",
                   admin_token)
    found = response.json().get('data') or []
    check('search by transaction id works', len(found) >= 1, str(len(found)))

    response = get('/admin/transaction-errors/summary', admin_token)
    summary = data_of(response)
    check('summary available', response.status_code == 200, response.text[:160])
    check('summary groups by type', len(summary.get('by_type') or []) >= 1)

    # -- Normal users must not reach any of it -----------------------------
    print('\nAuthorization')
    check('normal user refused the error list',
          get('/admin/transaction-errors', token).status_code == 403)
    check('normal user refused the summary',
          get('/admin/transaction-errors/summary', token).status_code == 403)

    return finish()


if __name__ == '__main__':
    sys.exit(main())
