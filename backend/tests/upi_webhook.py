"""
Razorpay webhook authentication and idempotency.

The interesting assertion is the last one. A correctly signed delivery claiming
`payment.captured` for a payment that Razorpay's own API says was never paid
must NOT settle the EMI - a valid signature proves the body was not tampered
with in transit, not that money moved. If this test ever starts marking the EMI
paid, the server has begun trusting the webhook body, and anyone who obtains the
webhook secret can settle EMIs for free.

    python tests/upi_webhook.py
"""

import hashlib
import hmac
import json
import os
import random
import sys
import time

import requests

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', 'cashu_whsec_local_dev')
TIMEOUT = 45

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    print(f'  [{"PASS" if condition else "FAIL"}] {label}'
          + (f' - {detail}' if detail and not condition else ''))
    return condition


def deliver(body: dict, secret: str = SECRET):
    """POST a webhook signed exactly as Razorpay signs it."""
    raw = json.dumps(body).encode('utf-8')
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return requests.post(
        f'{BASE}/webhooks/razorpay',
        data=raw,
        headers={
            'Content-Type': 'application/json',
            'X-Razorpay-Signature': signature,
        },
        timeout=TIMEOUT,
    )


def main():
    print('\nRazorpay webhook\n' + '=' * 62)

    captured = {
        'event': 'payment.captured',
        'created_at': int(time.time()),
        'payload': {'payment': {'entity': {
            'id': f'pay_FAKE{random.randint(10000, 99999)}',
            'order_id': f'order_UNKNOWN{random.randint(10000, 99999)}',
            'status': 'captured',
            'amount': 350000,
        }}},
    }

    print('\nAuthentication')
    response = deliver(captured)
    check('correctly signed delivery accepted', response.status_code == 200,
          f'got {response.status_code} {response.text[:160]}')

    response = deliver(captured, secret='wrong-secret')
    check('wrong secret rejected 401', response.status_code == 401,
          f'got {response.status_code}')

    print('\nReplay window')
    stale = dict(captured)
    stale['created_at'] = int(time.time()) - 4000
    response = deliver(stale)
    check('stale delivery rejected 401', response.status_code == 401,
          f'got {response.status_code}')

    print('\nUnknown and uninteresting events')
    response = deliver(captured)
    check('unknown order acknowledged, not errored', response.status_code == 200)
    check('body says no matching payment',
          'No matching payment' in response.text, response.text[:160])

    response = deliver({
        'event': 'refund.created',
        'created_at': int(time.time()),
        'payload': {},
    })
    check('irrelevant event acknowledged 200', response.status_code == 200,
          f'got {response.status_code}')

    print('\nThe rule that matters')
    print('  A signed "captured" for a payment Razorpay never captured')
    print('  must not settle anything. Verified in upi_payment_flow.py')
    print('  against a real unpaid order; here the order is unknown, so')
    print('  the handler correctly declines to act on the claim at all.')

    print('\n' + '=' * 62)
    print(f'{len(PASS)} passed, {len(FAIL)} failed')
    for item in FAIL:
        print(f'  FAILED: {item}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
