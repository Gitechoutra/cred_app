"""
End-to-end check of the Razorpay UPI EMI payment flow.

Runs against a live backend and the real Razorpay test rail. It deliberately
includes the attack cases, because the ones that matter here are not "does a
happy payment work" but "can a client talk its way into a paid EMI without
paying". Every assertion below that starts with `not` is one of those.

    python tests/upi_payment_flow.py
"""

import hashlib
import hmac
import json
import os
import random
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from throttle import throttled  # noqa: E402

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 45

PASS, FAIL, SKIP = [], [], []

#: The configured API secret, read rather than hardcoded. The point of the
#: leak checks below is that this exact value never appears in a response, and
#: pasting a fragment of it into a test file is its own small leak.
KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return condition


def skip(label, reason):
    """
    Record that a check could not run, rather than passing or failing it.

    The signature-attack cases below can only be proved against the real
    Razorpay rail. When the rail is simulated there is no gateway signature to
    forge, and the simulator settles by design - so asserting them would report
    a security hole that does not exist, and silently dropping them would claim
    coverage this run does not have.
    """
    SKIP.append(f'{label} ({reason})')
    print(f'  [SKIP] {label} - {reason}')


def leak_free(text):
    """
    Whether a response body is free of the API secret.

    Checks the configured secret itself, so rotating the key does not quietly
    turn this into a check of a stale string that can no longer appear.
    """
    if 'key_secret' in text:
        return False
    return not (KEY_SECRET and KEY_SECRET in text)


def post(path, body=None, token=None, idem=None):
    headers = {'X-Device-UUID': 'upi-flow-test'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem
    return throttled(lambda: requests.post(
        f'{BASE}{path}', json=body or {}, headers=headers, timeout=TIMEOUT))


def get(path, token=None):
    headers = {'X-Device-UUID': 'upi-flow-test'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return throttled(lambda: requests.get(
        f'{BASE}{path}', headers=headers, timeout=TIMEOUT))


def main():
    phone = f'9{random.randint(100000000, 999999999)}'
    print(f'\nRazorpay UPI flow - phone {phone}\n' + '=' * 62)

    # -- Sign in ----------------------------------------------------------
    print('\nAuth')
    response = post('/authentication/otp/send', {'phone': phone})
    otp = (response.json().get('data') or {}).get('debug_otp')
    if not check('OTP issued', response.status_code in (200, 201) and otp):
        return finish()

    response = post('/authentication/otp/verify', {'phone': phone, 'otp': otp})
    token = (response.json().get('data') or {}).get('access_token')
    if not check('signed in', bool(token)):
        return finish()

    post('/users/profile', {
        'full_name': 'UPI Test User',
        'email': f'upi.{phone}@example.com',
    }, token=token)

    # -- An EMI to pay ----------------------------------------------------
    print('\nEMI')
    response = post('/emi', {
        'provider_id': (get('/emi/providers', token).json().get('data') or [{}])[0].get('provider_id'),
        'loan_account_no': 'LAN4567890',
        'emi_amount': 2500,
        'due_day_of_month': 5,
        'total_tenure': 12,
        'tenure_remaining': 8,
    }, token=token, idem=f'emi-{phone}')

    emi = (response.json().get('data') or {})
    emi_id = emi.get('emi_id')
    if not check('EMI created', bool(emi_id), response.text[:200]):
        return finish()

    # -- Methods ----------------------------------------------------------
    print('\nPayment methods')
    response = get('/emi-payments/methods', token)
    methods = response.json().get('data') or {}
    upi = methods.get('upi') or {}

    check('UPI block present', bool(upi))

    # Which rail this run is actually on. A Razorpay account does not have UPI
    # enabled by default, and the server falls back to the simulator rather
    # than handing the user a checkout it cannot serve - so this is a property
    # of the merchant account, not a defect.
    live_rail = upi.get('provider') == 'RAZORPAY'
    if live_rail:
        check('provider is RAZORPAY', True)
    else:
        skip('provider is RAZORPAY',
             f'UPI is not enabled on the merchant account; rail is '
             f'{upi.get("provider")}')
    if live_rail:
        check('checkout key is a public test key',
              str(upi.get('checkout_key', '')).startswith('rzp_test_'))
    else:
        skip('checkout key is a public test key', 'simulated rail issues no key')
    check('Google Pay offered',
          any(a['id'] == 'google_pay' for a in upi.get('apps', [])))
    check('PhonePe offered',
          any(a['id'] == 'phonepe' for a in upi.get('apps', [])))
    check('no secret in the methods response',
          leak_free(response.text))
    check('credit card still prohibited',
          any(p['mode'] == 'CREDIT_CARD' for p in methods.get('prohibited', [])))

    # -- Initiate ---------------------------------------------------------
    print('\nInitiate UPI payment')
    response = post('/emi-payments', {
        'emi_id': emi_id,
        'payment_mode': 'UPI_INTENT',
        'upi_app': 'google_pay',
    }, token=token, idem=f'pay-{phone}-1')

    payment = (response.json().get('data') or {})
    payment_id = payment.get('payment_id')
    checkout = payment.get('checkout') or {}

    if not check('payment initiated', bool(payment_id), response.text[:300]):
        return finish()

    if live_rail:
        check('a real Razorpay order was opened',
              str(checkout.get('order_id', '')).startswith('order_'),
              str(checkout.get('order_id')))
    else:
        skip('a real Razorpay order was opened', 'simulated rail')
    # The provider adapter is authoritative over the installment amount, so
    # this asserts against the EMI the server resolved, not the number the
    # client happened to send.
    expected_paise = int(round(float(emi['emi_amount']) * 100))
    check('order amount matches the EMI exactly',
          checkout.get('amount_paise') == expected_paise,
          f'order {checkout.get("amount_paise")} vs EMI {expected_paise}')
    if live_rail:
        check('checkout key returned to client',
              str(checkout.get('key', '')).startswith('rzp_test_'))
    else:
        skip('checkout key returned to client', 'simulated rail issues no key')
    check('no secret in the initiate response', leak_free(response.text))
    check('status is PROCESSING, not paid', payment.get('status') == 'PROCESSING',
          str(payment.get('status')))
    check('chosen UPI app recorded', payment.get('upi_app') == 'google_pay')

    order_id = checkout.get('order_id')

    # -- Duplicate prevention --------------------------------------------
    print('\nDuplicate prevention')
    response = post('/emi-payments', {
        'emi_id': emi_id, 'payment_mode': 'UPI_INTENT',
    }, token=token, idem=f'pay-{phone}-2')
    check('second concurrent attempt refused', response.status_code == 409,
          f'got {response.status_code}')

    response = post('/emi-payments', {
        'emi_id': emi_id, 'payment_mode': 'UPI_INTENT',
    }, token=token, idem=f'pay-{phone}-1')
    check('replayed idempotency key returns the same payment',
          (response.json().get('data') or {}).get('payment_id') == payment_id)

    # -- Forged verification ---------------------------------------------
    print('\nForged verification (the case that matters)')
    # Only meaningful against the real rail. On the simulator there is no
    # gateway signature to forge and the simulated payment settles by design,
    # so these would report a hole that does not exist on the path that ships.
    if not live_rail:
        for label in ('forged signature did NOT settle the EMI',
                      'payload for another order rejected',
                      'payment still not marked paid after forgery attempts'):
            skip(label, 'signature forgery is not testable on the simulated rail')
    else:
        response = post(f'/emi-payments/{payment_id}/verify', {
            'razorpay_payment_id': 'pay_FORGED000000',
            'razorpay_order_id': order_id,
            'razorpay_signature': 'f' * 64,
        }, token=token)
        body = (response.json().get('data') or {})
        check('forged signature did NOT settle the EMI',
              body.get('status') not in ('SETTLED', 'SUCCESSFUL'),
              str(body.get('status')))

        response = post(f'/emi-payments/{payment_id}/verify', {
            'razorpay_payment_id': 'pay_SOMEONEELSE',
            'razorpay_order_id': 'order_NOTMINE0000',
            'razorpay_signature': 'a' * 64,
        }, token=token)
        check('payload for another order rejected',
              response.status_code == 400, f'got {response.status_code}')

        response = get(f'/emi-payments/{payment_id}', token)
        status = (response.json().get('data') or {}).get('status')
        check('payment still not marked paid after forgery attempts',
              status not in ('SETTLED', 'SUCCESSFUL'), str(status))

    # -- Unsigned webhook --------------------------------------------------
    print('\nWebhook authentication')
    response = requests.post(
        f'{BASE}/webhooks/razorpay',
        data=json.dumps({
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {
                'id': 'pay_EVIL', 'order_id': order_id, 'status': 'captured',
            }}},
        }),
        headers={'Content-Type': 'application/json'},
        timeout=TIMEOUT,
    )
    check('unsigned webhook rejected 401', response.status_code == 401,
          f'got {response.status_code}')

    response = requests.post(
        f'{BASE}/webhooks/razorpay',
        data=json.dumps({'event': 'payment.captured'}),
        headers={
            'Content-Type': 'application/json',
            'X-Razorpay-Signature': 'b' * 64,
        },
        timeout=TIMEOUT,
    )
    check('bad-signature webhook rejected 401', response.status_code == 401,
          f'got {response.status_code}')

    if live_rail:
        response = get(f'/emi-payments/{payment_id}', token)
        status = (response.json().get('data') or {}).get('status')
        check('payment still not paid after webhook forgery',
              status not in ('SETTLED', 'SUCCESSFUL'), str(status))
    else:
        skip('payment still not paid after webhook forgery',
             'the simulated payment has already settled')

    # The one that matters most. A *correctly signed* delivery claiming this
    # real order was captured, when Razorpay's own API says it was not. If the
    # server ever settles on this, anyone holding the webhook secret can clear
    # EMIs for free - the signature would have become the proof of payment
    # instead of merely the proof of authorship.
    secret = os.getenv('RAZORPAY_WEBHOOK_SECRET', 'cashu_whsec_local_dev')
    raw = json.dumps({
        'event': 'payment.captured',
        'created_at': int(time.time()),
        'payload': {'payment': {'entity': {
            'id': 'pay_CLAIMSCAPTURED',
            'order_id': order_id,
            'status': 'captured',
            'amount': expected_paise,
        }}},
    }).encode('utf-8')

    response = requests.post(
        f'{BASE}/webhooks/razorpay',
        data=raw,
        headers={
            'Content-Type': 'application/json',
            'X-Razorpay-Signature': hmac.new(
                secret.encode(), raw, hashlib.sha256
            ).hexdigest(),
        },
        timeout=TIMEOUT,
    )
    check('signed webhook for a real order is accepted',
          response.status_code == 200, f'got {response.status_code}')

    if live_rail:
        response = get(f'/emi-payments/{payment_id}', token)
        status = (response.json().get('data') or {}).get('status')
        check('SIGNED webhook claiming captured did NOT settle an unpaid EMI',
              status not in ('SETTLED', 'SUCCESSFUL'), str(status))
    else:
        skip('SIGNED webhook claiming captured did NOT settle an unpaid EMI',
             'needs a real order Razorpay can be asked about')

    # -- Cancel and retry --------------------------------------------------
    print('\nCancel and retry')
    if live_rail:
        response = post(f'/emi-payments/{payment_id}/cancel', token=token)
        cancelled = (response.json().get('data') or {})
        check('unpaid attempt cancels cleanly',
              cancelled.get('status') == 'CANCELLED',
              str(cancelled.get('status')))
    else:
        # Refusing to cancel a settled payment is correct behaviour, so there
        # is no unpaid attempt left to cancel on this rail.
        skip('unpaid attempt cancels cleanly',
             'the simulated payment settled, so nothing is unpaid to cancel')

    response = post('/emi-payments', {
        'emi_id': emi_id, 'payment_mode': 'UPI_COLLECT',
    }, token=token, idem=f'pay-{phone}-3')
    retry = (response.json().get('data') or {})
    check('a fresh attempt is allowed after cancelling',
          response.status_code == 201 and retry.get('payment_id') != payment_id,
          f'{response.status_code} {response.text[:160]}')
    check('retry opened a different order',
          (retry.get('checkout') or {}).get('order_id') != order_id)

    # -- Receipt gating ----------------------------------------------------
    print('\nReceipt')
    response = get(f'/emi-payments/{payment_id}/receipt', token)
    if live_rail:
        check('no receipt for an unpaid payment', response.status_code == 409,
              f'got {response.status_code}')
    else:
        # The simulated payment did settle, so a receipt is the right answer.
        # Asserting the gate needs a payment that never completed, which this
        # rail cannot produce.
        check('a settled payment does have a receipt',
              response.status_code == 200, f'got {response.status_code}')
        skip('no receipt for an unpaid payment',
             'the simulated payment settled, so it is entitled to a receipt')

    return finish()


def finish():
    print('\n' + '=' * 62)
    print(f'{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped')
    for item in FAIL:
        print(f'  FAILED: {item}')
    if SKIP:
        print('\nNOT VERIFIED BY THIS RUN')
        for item in SKIP:
            print(f'  {item}')
        print('\n  These are the gateway-signature guarantees. Enable UPI on '
              'the Razorpay\n  account and rerun to cover them.')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
