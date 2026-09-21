"""
End-to-end check of the Razorpay-funded transfer flow.

Mirrors tests/upi_payment_flow.py, for the other product. The assertions that
matter are the negative ones: a transfer moves real money out over IMPS, so the
question is not "does a happy payment work" but "can a client talk its way into
a dispatched payout without the card ever being charged".

    python tests/transfer_payment_flow.py
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

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 200


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    print(f'  [{"PASS" if condition else "FAIL"}] {label}'
          + (f' - {detail}' if detail and not condition else ''))
    return condition


def post(path, body=None, token=None, idem=None, form=None, files=None):
    headers = {'X-Device-UUID': 'transfer-flow-test'}
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
    headers = {'X-Device-UUID': 'transfer-flow-test'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return requests.get(f'{BASE}{path}', headers=headers, timeout=TIMEOUT)


def finish():
    print('\n' + '=' * 62)
    print(f'{len(PASS)} passed, {len(FAIL)} failed')
    for item in FAIL:
        print(f'  FAILED: {item}')
    return 1 if FAIL else 0


def main():
    phone = f'9{random.randint(100000000, 999999999)}'
    print(f'\nRazorpay transfer flow - phone {phone}\n' + '=' * 62)

    # -- Sign in ----------------------------------------------------------
    print('\nAuth')
    response = post('/authentication/otp/send', {'phone': phone})
    otp = (response.json().get('data') or {}).get('debug_otp')
    if not check('OTP issued', response.status_code in (200, 201) and otp,
                 response.text[:160]):
        return finish()

    response = post('/authentication/otp/verify', {'phone': phone, 'otp': otp})
    token = (response.json().get('data') or {}).get('access_token')
    if not check('signed in', bool(token)):
        return finish()

    post('/users/profile', {
        'full_name': 'Transfer Test User',
        'email': f'transfer.{phone}@example.com',
    }, token=token)
    post('/authentication/mpin/set', {'mpin': '246813'}, token=token)

    # -- Methods ----------------------------------------------------------
    print('\nPayment methods')
    response = get('/transfers/methods', token)
    methods = response.json().get('data') or {}

    check('methods endpoint responds', response.status_code == 200,
          response.text[:200])
    check('credit card is a funding instrument',
          any(m['mode'] == 'CREDIT_CARD' for m in methods.get('permitted', [])))

    # UPI funding follows the key: offered on a test key, withheld on a live
    # one unless TRANSFER_UPI_FUNDING says otherwise. Assert whichever the
    # server reports, and that the *other* branch is explained rather than
    # silently absent.
    upi = methods.get('upi') or {}
    if upi.get('enabled'):
        check('UPI offered for testing',
              any(m['mode'] == 'UPI' for m in methods.get('permitted', [])))
        check('Google Pay offered',
              any(a['id'] == 'google_pay' for a in upi.get('apps', [])))
        check('PhonePe offered',
              any(a['id'] == 'phonepe' for a in upi.get('apps', [])))
        check('a VPA is prefilled for testing', bool(upi.get('test_vpa')),
              str(upi.get('test_vpa')))
    else:
        check('UPI is explained, not silently missing',
              any('UPI' in p.get('label', '')
                  for p in methods.get('prohibited', [])))
    check('checkout key is a public test key',
          str((methods.get('checkout') or {}).get('key', '')).startswith('rzp_test_'),
          str((methods.get('checkout') or {}).get('key')))
    check('no secret in the methods response',
          'q3QQR8' not in response.text and 'key_secret' not in response.text)

    # -- Setup: KYC, card, bank -------------------------------------------
    print('\nSetup')
    response = post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F',
        'full_name': 'Transfer Test User',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', PNG, 'image/png')}, token=token)
    if not check('KYC submitted', response.status_code in (200, 201),
                 response.text[:200]):
        return finish()

    admin = post('/authentication/mpin/verify',
                 {'phone': '9999999999', 'mpin': '135790'})
    if not check('admin signed in', admin.status_code == 200, admin.text[:160]):
        return finish()
    admin_token = admin.json()['data']['access_token']

    queue = get('/admin/kyc/queue', admin_token).json().get('data') or []
    mine = [k for k in queue
            if (k.get('masked_phone') or '').endswith(phone[-4:])]
    if not check('submission reached the queue', len(mine) == 1, str(len(mine))):
        return finish()

    response = post(f"/admin/kyc/{mine[0]['kyc_id']}/review",
                    {'decision': 'APPROVE', 'tier': 'MINIMUM'},
                    token=admin_token)
    check('KYC approved by admin', response.status_code == 200,
          response.text[:200])

    # Re-issue the token so it carries the new tier claim.
    response = post('/authentication/mpin/verify',
                    {'phone': phone, 'mpin': '246813'})
    if response.status_code == 200:
        token = response.json()['data']['access_token']

    response = post('/cards', {
        'bin': '455614', 'last4': '4821',
        'expiry_month': '12', 'expiry_year': '2030',
        'cardholder_name': 'TRANSFER TEST USER',
        'card_limit': 300000, 'due_day': 10,
    }, token=token)
    card_id = (response.json().get('data') or {}).get('card_id')
    if not check('card linked', bool(card_id), response.text[:250]):
        return finish()

    account_number = f'5010{random.randint(10000000, 99999999)}'
    response = post('/bank-accounts', {
        'account_number': account_number,
        'confirm_account_number': account_number,
        'ifsc_code': 'HDFC0001234',
        'account_type': 'SAVINGS',
        'account_holder_name': 'Transfer Test User',
        'is_primary': True,
    }, token=token)
    bank_id = (response.json().get('data') or {}).get('bank_account_id')
    if not check('bank account added', bool(bank_id), response.text[:250]):
        return finish()

    # -- Initiate ---------------------------------------------------------
    print('\nInitiate transfer')
    response = post('/transfers', {
        'card_id': card_id, 'bank_account_id': bank_id, 'amount': 5000,
    }, token=token, idem=f'txn-{phone}-1')

    transfer = (response.json().get('data') or {})
    transfer_id = transfer.get('transfer_id')
    checkout = transfer.get('checkout') or {}

    if not check('transfer initiated', bool(transfer_id), response.text[:300]):
        return finish()

    check('routed through Razorpay', checkout.get('provider') == 'RAZORPAY',
          str(checkout.get('provider')))
    check('a real Razorpay order was opened',
          str(checkout.get('order_id', '')).startswith('order_'),
          str(checkout.get('order_id')))

    # The order must be for the total charged to the card - principal plus fee
    # plus GST - not the principal alone, or CashU eats the fee.
    expected = int(round(float(transfer['total_charged_to_card']) * 100))
    check('order amount is principal + fee + GST',
          checkout.get('amount_paise') == expected,
          f'order {checkout.get("amount_paise")} vs expected {expected}')
    check('no secret in the initiate response', 'q3QQR8' not in response.text)
    check('status is AUTH_PENDING, not charged',
          transfer.get('status') == 'AUTH_PENDING', str(transfer.get('status')))

    order_id = checkout.get('order_id')

    # -- Forged verification ----------------------------------------------
    print('\nForged verification (the case that matters)')
    settled = ('SUCCEEDED', 'PAYOUT_PROCESSING', 'INBOUND_CHARGED')

    response = post(f'/transfers/{transfer_id}/verify', {
        'razorpay_payment_id': 'pay_FORGED000000',
        'razorpay_order_id': order_id,
        'razorpay_signature': 'f' * 64,
    }, token=token)
    body = (response.json().get('data') or {})
    check('forged signature did NOT complete the transfer',
          body.get('status') not in settled, str(body.get('status')))

    response = post(f'/transfers/{transfer_id}/verify', {
        'razorpay_payment_id': 'pay_SOMEONEELSE',
        'razorpay_order_id': 'order_NOTMINE0000',
        'razorpay_signature': 'a' * 64,
    }, token=token)
    check('payload for another order rejected', response.status_code == 400,
          f'got {response.status_code}')

    # -- Signed webhook on an unpaid order ---------------------------------
    print('\nSigned webhook claiming the card was charged')
    raw = json.dumps({
        'event': 'payment.captured',
        'created_at': int(time.time()),
        'payload': {'payment': {'entity': {
            'id': 'pay_CLAIMSCAPTURED',
            'order_id': order_id,
            'status': 'captured',
            'amount': expected,
        }}},
    }).encode('utf-8')

    response = requests.post(
        f'{BASE}/webhooks/razorpay',
        data=raw,
        headers={
            'Content-Type': 'application/json',
            'X-Razorpay-Signature': hmac.new(
                SECRET.encode(), raw, hashlib.sha256).hexdigest(),
        },
        timeout=TIMEOUT,
    )
    check('signed webhook for a real transfer is accepted',
          response.status_code == 200, f'got {response.status_code}')
    check('webhook resolved it to the transfer, not an EMI',
          'transfer' in response.text.lower(), response.text[:200])

    response = get(f'/transfers/{transfer_id}', token)
    status = (response.json().get('data') or {}).get('status')
    check('SIGNED webhook did NOT charge an uncharged card',
          status not in settled, str(status))

    # -- No payout without a charge ---------------------------------------
    print('\nNo payout without a charge')
    detail = (get(f'/transfers/{transfer_id}', token).json().get('data') or {})
    check('no UTR was issued', not detail.get('utr'), str(detail.get('utr')))
    check('nothing was charged to the card', not detail.get('charged_at'),
          str(detail.get('charged_at')))

    response = get(f'/transfers/{transfer_id}/receipt', token)
    check('no receipt for an incomplete transfer',
          response.status_code in (400, 409), f'got {response.status_code}')

    return finish()


if __name__ == '__main__':
    sys.exit(main())
