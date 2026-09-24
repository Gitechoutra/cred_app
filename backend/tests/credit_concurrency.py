"""
Concurrency on a credit line.

The sequential lifecycle suite cannot test the thing the row locking exists for.
It walks one request at a time, so `SELECT ... FOR UPDATE` could be deleted from
credit_engine and every one of its 121 checks would still pass. This file fires
simultaneous requests at one account and asserts what has to be true afterwards:

    1. Two purchases that each fit but together do not: exactly one succeeds.
       Without the lock both read the same available balance, both pass the
       check, and the account ends up overdrawn.

    2. The same idempotency key sent N times at once: exactly one transaction
       exists. This is the UNIQUE index doing the work, not the pre-read, which
       cannot close the window between concurrent requests.

    3. Simultaneous purchases that all fit: every one lands, nothing is lost,
       and the balances still add up. A lock that serialises correctly must not
       also drop writes.

Run with the server up. Threads, not processes, because the contention that
matters is at the database rather than in Python:

    python tests/credit_concurrency.py
"""

import os
import random
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from throttle import throttled  # noqa: E402

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 60

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def post(path, body=None, token=None, idem=None, form=None, files=None,
         retry_throttle=True):
    headers = {'X-Device-UUID': 'credit-concurrency'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem

    def send():
        if files or form:
            return requests.post(f'{BASE}{path}', data=form, files=files,
                                 headers=headers, timeout=TIMEOUT)
        return requests.post(f'{BASE}{path}', json=body or {}, headers=headers,
                             timeout=TIMEOUT)

    # The racing calls must NOT retry: a retry would serialise them, which is
    # precisely the contention this file exists to create.
    return throttled(send) if retry_throttle else send()


def get(path, token=None):
    headers = {'X-Device-UUID': 'credit-concurrency'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return throttled(lambda: requests.get(
        f'{BASE}{path}', headers=headers, timeout=TIMEOUT))


def data_of(response):
    try:
        return response.json().get('data') or {}
    except ValueError:
        return {}


def make_user(name):
    phone = f'9{random.randint(100000000, 999999999)}'
    otp = data_of(post('/authentication/otp/send', {'phone': phone})).get('debug_otp')
    if not otp:
        return None
    token = data_of(
        post('/authentication/otp/verify', {'phone': phone, 'otp': otp})
    ).get('access_token')
    if token:
        post('/authentication/register',
             {'full_name': name, 'terms_accepted': True}, token=token)
        post('/authentication/mpin/set', {'mpin': '246813'}, token=token)
    return token


def admin_token():
    return data_of(post('/authentication/mpin/verify', {
        'phone': os.getenv('ADMIN_SEED_PHONE', '9999999999'),
        'mpin': os.getenv('ADMIN_SEED_MPIN', '135790'),
    })).get('access_token')


def spendable_account(token, admin, name, limit):
    """Take a fresh user all the way to an active credit line."""
    user_id = data_of(get('/users/me', token)).get('user_id')

    png = b'\x89PNG\r\n\x1a\n' + b'0' * 400
    post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F', 'full_name': name,
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', png, 'image/png')}, token=token)

    queue = data_of(get('/admin/kyc/queue', admin))
    rows = queue if isinstance(queue, list) else (queue.get('items') or [])
    kyc_id = next((r['kyc_id'] for r in rows if r.get('user_id') == user_id), None)
    if not kyc_id:
        return None
    post(f'/admin/kyc/{kyc_id}/review',
         {'decision': 'APPROVE', 'tier': 'MINIMUM'}, token=admin)

    application = data_of(post('/credit/applications', {
        'employment_type': 'SALARIED', 'monthly_income': 200000,
    }, token=token))
    if not application.get('application_id'):
        return None

    post(f"/admin/credit/applications/{application['application_id']}/review",
         {'decision': 'APPROVE', 'limit': limit}, token=admin)

    post('/credit/account/purpose', {'purpose': 'SHOPPING'}, token=token)
    post('/credit/account/activate', token=token)

    account = data_of(get('/credit/account', token))
    return account if account.get('status') == 'ACTIVE' else None


def invariant_holds(token):
    account = data_of(get('/credit/account', token))
    return (
        round(account['available_credit'] + account['current_outstanding'], 2)
        == round(account['credit_limit'], 2)
    ), account


def main():
    print('\nCredit line concurrency\n' + '=' * 66)

    admin = admin_token()
    if not check('administrator login', bool(admin)):
        return finish()

    # ── 1. Two purchases that together exceed the limit ───────────────────
    print('\n[1] Racing purchases that together overdraw the limit')
    token = make_user('Race One')
    if not check('signed in', bool(token)):
        return finish()

    account = spendable_account(token, admin, 'Race One', 10000)
    if not check('active credit line with a 10,000 limit',
                 bool(account) and account['credit_limit'] == 10000,
                 str(account)):
        return finish()

    # 6,000 each against a 10,000 limit. Each fits on its own; together they do
    # not. Without the row lock both read 10,000 available and both succeed.
    def buy(amount, merchant):
        return post('/credit/purchases',
                    {'amount': amount, 'merchant_name': merchant},
                    token=token, idem=uuid.uuid4().hex, retry_throttle=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(buy, 6000, 'Racer A'),
            pool.submit(buy, 6000, 'Racer B'),
        ]
        results = [f.result() for f in futures]

    created = [r for r in results if r.status_code == 201]
    refused = [r for r in results if r.status_code == 400]

    check('exactly one of the two racing purchases succeeded',
          len(created) == 1,
          f'{len(created)} created, statuses {[r.status_code for r in results]}')
    check('the other was refused for insufficient credit',
          len(refused) == 1
          and refused[0].json().get('error', {}).get('code')
              == 'INSUFFICIENT_CREDIT',
          str([r.json().get('error', {}).get('code') for r in refused]))

    ok, account = invariant_holds(token)
    check('the account is not overdrawn',
          account['current_outstanding'] == 6000,
          f"outstanding {account['current_outstanding']}")
    check('available credit is correct after the race',
          account['available_credit'] == 4000,
          f"available {account['available_credit']}")
    check('the invariant survived the race', ok, str(account))

    # ── 2. One idempotency key sent many times at once ─────────────────────
    print('\n[2] One idempotency key, eight simultaneous requests')
    token_two = make_user('Race Two')
    account = spendable_account(token_two, admin, 'Race Two', 20000)
    if not check('second active credit line', bool(account), str(account)):
        return finish()

    shared_key = uuid.uuid4().hex

    def replay():
        return post('/credit/purchases',
                    {'amount': 1500, 'merchant_name': 'Double Tap'},
                    token=token_two, idem=shared_key, retry_throttle=False)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [pool.submit(replay) for _ in range(8)]]

    accepted = [r for r in results if r.status_code in (200, 201)]
    check('every concurrent replay got an answer, none errored',
          len(accepted) == 8,
          f'statuses {sorted(r.status_code for r in results)}')

    ids = {
        data_of(r).get('transaction', {}).get('credit_transaction_id')
        for r in accepted
    }
    check('all eight resolved to one transaction', len(ids) == 1, str(ids))

    history = get('/credit/transactions', token_two).json().get('data') or []
    check('exactly one transaction was recorded', len(history) == 1,
          f'{len(history)} rows')
    check('the card was charged once, not eight times',
          data_of(get('/credit/account', token_two))['current_outstanding'] == 1500,
          str(data_of(get('/credit/account', token_two))['current_outstanding']))

    ok, account = invariant_holds(token_two)
    check('the invariant survived the replay storm', ok, str(account))

    # ── 3. Simultaneous purchases that all fit ────────────────────────────
    print('\n[3] Six simultaneous purchases that all fit')
    token_three = make_user('Race Three')
    account = spendable_account(token_three, admin, 'Race Three', 30000)
    if not check('third active credit line', bool(account), str(account)):
        return finish()

    # 6 x 1,000 against 30,000. All should land: serialising correctly must not
    # mean dropping writes.
    def buy_small(index):
        return post('/credit/purchases',
                    {'amount': 1000, 'merchant_name': f'Shop {index}'},
                    token=token_three, idem=uuid.uuid4().hex,
                    retry_throttle=False)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in
                   [pool.submit(buy_small, i) for i in range(6)]]

    created = [r for r in results if r.status_code == 201]
    check('all six purchases landed', len(created) == 6,
          f'statuses {sorted(r.status_code for r in results)}')

    account = data_of(get('/credit/account', token_three))
    check('the outstanding balance is the sum of all six',
          account['current_outstanding'] == 6000,
          f"outstanding {account['current_outstanding']}")
    check('no write was lost', account['available_credit'] == 24000,
          f"available {account['available_credit']}")

    ok, account = invariant_holds(token_three)
    check('the invariant survived concurrent writes', ok, str(account))

    # Each transaction's balance_after must be distinct: two rows claiming the
    # same balance would mean both were computed from the same stale read, even
    # if the final total happened to come out right.
    history = get('/credit/transactions', token_three).json().get('data') or []
    balances = sorted(t['balance_after'] for t in history)
    check('each purchase recorded a distinct running balance',
          balances == [1000, 2000, 3000, 4000, 5000, 6000], str(balances))

    return finish()


def finish():
    print('\n' + '=' * 66)
    print(f'{len(PASS)} passed, {len(FAIL)} failed')
    if FAIL:
        print('\nFAILURES')
        for item in FAIL:
            print(f'  {item}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
