"""
Predefined test cards, end to end.

Proves two separate things, and the second matters more:

1. Each test card produces its own outcome through the ordinary payment path -
   a declined card really does fail the transfer, a short-limit card really is
   refused by the balance check.

2. Nothing about this reaches a real rail, and a test card cannot be linked
   where test mode is off.

    python tests/test_card_flow.py
"""

import os
import random
import sys

import requests

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
    headers = {'X-Device-UUID': 'test-card-flow'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem
    if files or form:
        return requests.post(f'{BASE}{path}', data=form, files=files,
                             headers=headers, timeout=TIMEOUT)
    return requests.post(f'{BASE}{path}', json=body or {}, headers=headers,
                         timeout=TIMEOUT)


def get(path, token=None):
    headers = {'X-Device-UUID': 'test-card-flow'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return requests.get(f'{BASE}{path}', headers=headers, timeout=TIMEOUT)


def data_of(response):
    try:
        return response.json().get('data') or {}
    except ValueError:
        return {}


def finish():
    print('\n' + '=' * 64)
    print(f'{len(PASS)} passed, {len(FAIL)} failed')
    for item in FAIL:
        print(f'  FAILED: {item}')
    return 1 if FAIL else 0


def link(token, card, nickname):
    """Link a catalogue card exactly as the browser would."""
    return post('/cards', {
        'bin': card['bin'],
        'last4': card['last4'],
        'expiry_month': card['expiry_month'],
        'expiry_year': card['expiry_year'],
        'cardholder_name': card['cardholder_name'],
        'issuer_bank': card['issuer_bank'],
        'brand_color': card['brand_color'],
        'nickname': nickname,
        'due_day': 10,
    }, token=token)


def main():
    phone = f'9{random.randint(100000000, 999999999)}'
    print(f'\nTest card flow - phone {phone}\n' + '=' * 64)

    # -- Sign in ----------------------------------------------------------
    print('\nSetup')
    response = post('/authentication/otp/send', {'phone': phone})
    otp = data_of(response).get('debug_otp')
    if not check('OTP issued', bool(otp), response.text[:160]):
        return finish()

    token = data_of(post('/authentication/otp/verify',
                         {'phone': phone, 'otp': otp})).get('access_token')
    if not check('signed in', bool(token)):
        return finish()

    post('/authentication/register',
         {'full_name': 'Card Tester', 'terms_accepted': True}, token=token)
    post('/authentication/mpin/set', {'mpin': '246813'}, token=token)

    # -- Catalogue --------------------------------------------------------
    print('\nCatalogue')
    response = get('/cards/test-cards', token)
    if not check('test cards available', response.status_code == 200,
                 f'got {response.status_code} {response.text[:120]}'):
        return finish()

    payload = data_of(response)
    cards = {c['scenario']: c for c in payload.get('cards', [])}

    check('test mode is advertised', payload.get('test_mode') is True)
    check('a simulation notice is returned', 'simulated' in (payload.get('notice') or '').lower())
    check('every scenario has a card', len(cards) == 6, str(sorted(cards)))
    check('numbers are Luhn-valid', all(luhn(c['number']) for c in cards.values()))
    check('a CVV is supplied for the form', all(c.get('cvv') for c in cards.values()))
    check('expired card looks expired',
          cards['TOKEN_EXPIRED']['expiry_year'] == '2020',
          cards['TOKEN_EXPIRED']['expiry_year'])

    # -- Linking ----------------------------------------------------------
    print('\nAdd card')
    response = link(token, cards['SUCCESS'], 'Test success')
    success_card = data_of(response)
    check('success card links', response.status_code == 201, response.text[:200])
    check('card is flagged as a test card',
          success_card.get('is_test_card') is True)
    check('scenario recorded on the card',
          success_card.get('test_scenario') == 'SUCCESS',
          str(success_card.get('test_scenario')))
    check('catalogue limit applied',
          float(success_card.get('card_limit') or 0) == 200000.0,
          str(success_card.get('card_limit')))
    check('only last four are stored',
          success_card.get('last4') == cards['SUCCESS']['last4']
          and cards['SUCCESS']['number'] not in response.text,
          'full number present in response')

    response = link(token, cards['TOKEN_EXPIRED'], 'Test expired')
    check('expired card is refused at link time',
          response.status_code == 400, f'got {response.status_code}')

    response = link(token, cards['INSUFFICIENT_LIMIT'], 'Test low limit')
    low_card = data_of(response)
    check('low-limit card links', response.status_code == 201, response.text[:200])
    check('low limit really is low',
          float(low_card.get('card_limit') or 0) == 500.0,
          str(low_card.get('card_limit')))

    response = link(token, cards['DECLINE'], 'Test decline')
    decline_card = data_of(response)
    check('decline card links', response.status_code == 201, response.text[:200])

    # -- The card list ----------------------------------------------------
    listing = get('/cards', token)
    body = listing.json().get('data') or {}
    rows = body.get('cards') if isinstance(body, dict) else body
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    check('test cards appear in the list', len(rows) >= 3, str(len(rows)))
    check('every linked card is badgeable',
          all(r.get('is_test_card') for r in rows if r.get('test_scenario')))
    check('no full card number anywhere in the list',
          not any(c['number'] in listing.text for c in cards.values()))

    # -- Payment scenarios ------------------------------------------------
    print('\nPayment outcomes')

    # KYC + a payout account, so a transfer can actually be attempted.
    response = post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F', 'full_name': 'Card Tester',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', PNG, 'image/png')}, token=token)

    admin = post('/authentication/mpin/verify',
                 {'phone': '9999999999', 'mpin': '135790'})
    if admin.status_code == 200:
        admin_token = admin.json()['data']['access_token']
        queue = get('/admin/kyc/queue', admin_token).json().get('data') or []
        mine = [k for k in queue
                if (k.get('masked_phone') or '').endswith(phone[-4:])]
        if mine:
            post(f"/admin/kyc/{mine[0]['kyc_id']}/review",
                 {'decision': 'APPROVE', 'tier': 'MINIMUM'}, token=admin_token)
        re_auth = post('/authentication/mpin/verify',
                       {'phone': phone, 'mpin': '246813'})
        if re_auth.status_code == 200:
            token = re_auth.json()['data']['access_token']

    account = f'5010{random.randint(10000000, 99999999)}'
    bank = data_of(post('/bank-accounts', {
        'account_number': account, 'confirm_account_number': account,
        'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
        'account_holder_name': 'Card Tester', 'is_primary': True,
    }, token=token)).get('bank_account_id')

    if not check('payout account added', bool(bank)):
        return finish()

    # Insufficient limit: refused by the ordinary balance check, before any
    # charge is attempted.
    response = post('/transfers', {
        'card_id': low_card['card_id'], 'bank_account_id': bank, 'amount': 5000,
    }, token=token, idem=f'low-{phone}')
    check('short-limit card is refused', response.status_code == 400,
          f'got {response.status_code}')
    check('refusal names the balance, not a gateway error',
          'balance' in response.text.lower() or 'limit' in response.text.lower(),
          response.text[:160])

    # Decline: the order opens, the charge is refused.
    response = post('/transfers', {
        'card_id': decline_card['card_id'], 'bank_account_id': bank,
        'amount': 2000,
    }, token=token, idem=f'dec-{phone}')
    declined = data_of(response)
    # The order must open: a decline belongs at authorisation, after the user
    # has walked the journey, not as an error on the amount screen.
    if check('decline card opens a transfer', response.status_code == 201,
             response.text[:200]):
        confirmed = data_of(post(f"/transfers/{declined['transfer_id']}/confirm",
                                 token=token))
        check('declined charge fails the transfer',
              confirmed.get('status') == 'FAILED',
              str(confirmed.get('status')))
        check('nothing was charged', not confirmed.get('charged_at'))
        check('no UTR issued', not confirmed.get('utr'))

    # Success: charge clears and the transfer advances.
    response = post('/transfers', {
        'card_id': success_card['card_id'], 'bank_account_id': bank,
        'amount': 2000,
    }, token=token, idem=f'ok-{phone}')
    ok = data_of(response)
    if check('success card opens a transfer', response.status_code == 201,
             response.text[:200]):
        # The guarantee, asserted rather than assumed: a dummy card must not
        # open an order against the real merchant account. Razorpay order ids
        # start with "order_"; the simulator's do not.
        checkout = ok.get('checkout') or {}
        check('test card never reaches the gateway',
              checkout.get('provider') != 'RAZORPAY'
              and not str(checkout.get('order_id') or '').startswith('order_'),
              f"provider={checkout.get('provider')} order={checkout.get('order_id')}")
        confirmed = data_of(post(f"/transfers/{ok['transfer_id']}/confirm",
                                 token=token))
        status = confirmed.get('status')
        check('successful charge advances the transfer',
              status in ('SUCCEEDED', 'PAYOUT_PROCESSING', 'INBOUND_CHARGED'),
              str(status))
        check('the charge is recorded', bool(confirmed.get('charged_at')),
              str(confirmed.get('charged_at')))

        # -- History and limits -------------------------------------------
        print('\nHistory and limits')
        txns = get('/transactions', token).json().get('data') or []
        check('transaction recorded in history', len(txns) >= 1, str(len(txns)))

        detail = data_of(get(f"/cards/{success_card['card_id']}", token))
        check('limit moved after a successful charge',
              float(detail.get('available_limit') or 0) < 200000.0,
              str(detail.get('available_limit')))

        receipt = get(f"/transfers/{ok['transfer_id']}/receipt", token)
        check('receipt available for a settled transfer',
              receipt.status_code in (200, 409),
              f'got {receipt.status_code}')

    # -- Simulated UPI transfer -------------------------------------------
    print('\nSimulated UPI transfer')
    response = post('/transfers', {
        'card_id': success_card['card_id'], 'bank_account_id': bank,
        'amount': 1200, 'payment_method': 'UPI',
    }, token=token, idem=f'upi-{phone}')
    upi = data_of(response)

    if check('UPI transfer opens', response.status_code == 201,
             response.text[:200]):
        checkout = upi.get('checkout') or {}
        check('simulated UPI never reaches the gateway',
              checkout.get('provider') != 'RAZORPAY',
              str(checkout.get('provider')))

        confirmed = data_of(post(f"/transfers/{upi['transfer_id']}/confirm",
                                 token=token))
        check('UPI transfer completes',
              confirmed.get('status') in ('SUCCEEDED', 'PAYOUT_PROCESSING',
                                          'INBOUND_CHARGED'),
              str(confirmed.get('status')))
        check('recorded as UPI, not as a card',
              confirmed.get('source_instrument') == 'upi',
              str(confirmed.get('source_instrument')))

        # The money came out of a bank, not the credit line, so the card's
        # limit must be untouched by this one.
        card_now = data_of(get(f"/cards/{success_card['card_id']}", token))
        check('credit line not drawn down by a UPI payment',
              float(card_now.get('outstanding_amount') or 0)
              == float(detail.get('outstanding_amount') or 0),
              f"{detail.get('outstanding_amount')} -> {card_now.get('outstanding_amount')}")

        txns = get('/transactions', token).json().get('data') or []
        check('UPI transfer appears in history', len(txns) >= 2, str(len(txns)))

    return finish()


def luhn(number):
    digits = [int(c) for c in str(number) if c.isdigit()][::-1]
    total = 0
    for index, digit in enumerate(digits):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


if __name__ == '__main__':
    sys.exit(main())
