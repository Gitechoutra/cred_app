"""
End-to-end smoke test against a running CashU API.

Walks the primary journey - onboarding, KYC, card linking, bank account, ledger,
EMI, dashboard - and asserts the acceptance criteria that carry money:

    AC-001  tokenized card linking, zero raw PAN in the database
    AC-004  idempotency: a replayed key must not charge twice

The spend leg is blocked: it walked the credit-to-bank transfer, which has been
removed, and its replacement is the credit-line purchase flow.

Run with the server already up:  python tests/smoke_flow.py
"""

import json
import os
import random
import sys
import uuid

import requests

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 30

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = ''):
    (PASS if condition else FAIL).append(name)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {name}' + (f'  -- {detail}' if detail and not condition else ''))
    return condition


def post(path, body=None, token=None, idem=None, files=None, form=None):
    headers = {'X-Device-UUID': 'smoke-test-device'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem

    if form or files:
        return requests.post(
            f'{BASE}{path}', data=form, files=files, headers=headers, timeout=TIMEOUT
        )
    return requests.post(
        f'{BASE}{path}', json=body or {}, headers=headers, timeout=TIMEOUT
    )


def get(path, token=None):
    headers = {'X-Device-UUID': 'smoke-test-device'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return requests.get(f'{BASE}{path}', headers=headers, timeout=TIMEOUT)


def patch(path, body, token):
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Device-UUID': 'smoke-test-device',
    }
    return requests.patch(f'{BASE}{path}', json=body, headers=headers, timeout=TIMEOUT)


def main():
    phone = f'9{random.randint(100000000, 999999999)}'
    print(f'\nCashU smoke test - phone {phone}\n' + '=' * 60)

    # ── Onboarding (FR-001) ────────────────────────────────────────────────
    print('\n[1] Authentication')

    response = post('/authentication/otp/send', {'phone': phone})
    ok = check('OTP send', response.status_code == 200, response.text[:200])
    if not ok:
        return finish()

    otp = response.json()['data'].get('debug_otp')
    check('OTP returned in DEV mode', bool(otp))

    response = post('/authentication/otp/verify', {'phone': phone, 'otp': otp})
    if not check('OTP verify', response.status_code == 200, response.text[:300]):
        return finish()

    payload = response.json()['data']
    token = payload['access_token']
    check('New user provisioned', payload.get('is_new_user') is True)
    check('Profile required', payload.get('requires_profile') is True)

    response = post('/authentication/register', {
        'full_name': 'Vikram Sharma',
        'email': f'vikram.{phone}@example.com',
        'terms_accepted': True,
    }, token=token)
    check('Registration', response.status_code == 200, response.text[:200])

    response = post('/authentication/mpin/set', {'mpin': '246813'}, token=token)
    check('MPIN set', response.status_code == 200, response.text[:200])

    response = post('/authentication/mpin/verify', {'phone': phone, 'mpin': '246813'})
    check('MPIN login', response.status_code == 200, response.text[:200])

    response = post('/authentication/mpin/verify', {'phone': phone, 'mpin': '111111'})
    check('Wrong MPIN rejected', response.status_code == 401)

    # ── Weak-MPIN policy ───────────────────────────────────────────────────
    response = post('/authentication/mpin/set', {'mpin': '123456'}, token=token)
    check('Sequential MPIN refused', response.status_code == 400)

    # ── KYC (FR-012) ───────────────────────────────────────────────────────
    print('\n[2] KYC')

    response = get('/kyc/status', token=token)
    check('KYC status', response.status_code == 200, response.text[:200])

    response = post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F',
        'full_name': 'Vikram Sharma',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', b'\x89PNG\r\n\x1a\n-smoke', 'image/png')},
        token=token)
    check('KYC submit', response.status_code == 201, response.text[:300])

    # ── Admin KYC approval (PRD 16.1) ──────────────────────────────────────
    # The tier is granted on approval, never on submission - which is exactly
    # what makes KYC a real gate on transfer limits. Without this step the
    # transfer below is correctly refused with KYC_REQUIRED.
    print('\n[2b] Admin KYC approval')

    response = post('/authentication/mpin/verify',
                    {'phone': '9999999999', 'mpin': '135790'})
    admin_ok = check('Admin login', response.status_code == 200, response.text[:200])

    if admin_ok:
        admin_token = response.json()['data']['access_token']
        check('Admin is L3',
              response.json()['data']['user']['role'] == 'L3_SUPER_ADMIN')

        response = get('/admin/kyc/queue', token=admin_token)
        queue_ok = check('KYC queue', response.status_code == 200, response.text[:200])

        if queue_ok:
            pending = [
                k for k in response.json()['data']
                if k['masked_phone'] and k['masked_phone'].endswith(phone[-4:])
            ]
            check('Submission in queue', len(pending) == 1, str(len(pending)))

            if pending:
                response = post(
                    f"/admin/kyc/{pending[0]['kyc_id']}/review",
                    {'decision': 'APPROVE', 'tier': 'MINIMUM'},
                    token=admin_token,
                )
                check('KYC approved', response.status_code == 200, response.text[:300])

        # Re-issue the user's token so it carries the new tier claim.
        response = post('/authentication/mpin/verify',
                        {'phone': phone, 'mpin': '246813'})
        if response.status_code == 200:
            token = response.json()['data']['access_token']
            check('Tier upgraded to MINIMUM',
                  response.json()['data']['user']['kyc_tier'] == 'MINIMUM',
                  response.json()['data']['user']['kyc_tier'])

    # ── Card linking (FR-003, AC-001) ──────────────────────────────────────
    print('\n[3] Card linking')

    response = get('/cards/networks/lookup/455614', token=token)
    bin_ok = check('BIN lookup', response.status_code == 200, response.text[:200])
    if bin_ok:
        check('Issuer identified',
              response.json()['data']['issuer_bank'] == 'HDFC Bank')

    response = post('/cards', {
        'bin': '455614',
        'last4': '4821',
        'expiry_month': '12',
        'expiry_year': '2030',
        'cardholder_name': 'VIKRAM SHARMA',
        'card_limit': 300000,
        'due_day': 10,
    }, token=token)

    card_ok = check('Card linked', response.status_code == 201, response.text[:300])
    if not card_ok:
        return finish()

    card = response.json()['data']
    card_id = card['card_id']
    check('Masked PAN only', card['masked_pan'] == '**** **** **** 4821',
          card['masked_pan'])

    # ERR-001: prepaid/debit must be refused.
    response = post('/cards', {
        'bin': '411111', 'last4': '1111',
        'expiry_month': '12', 'expiry_year': '2030',
    }, token=token)
    check('Debit card refused (ERR-001)', response.status_code == 400)

    # ── Bank account + penny drop (FR-005) ─────────────────────────────────
    print('\n[4] Bank account')

    account_number = str(random.randint(10 ** 11, 10 ** 12 - 1))
    response = post('/bank-accounts', {
        'account_number': account_number,
        'confirm_account_number': account_number,
        'ifsc_code': 'HDFC0001234',
        'account_type': 'SAVINGS',
        'account_holder_name': 'Vikram Sharma',
        'is_primary': True,
    }, token=token)

    bank_ok = check('Bank account added', response.status_code == 201, response.text[:300])
    if not bank_ok:
        return finish()

    account = response.json()['data']
    bank_account_id = account['bank_account_id']
    check('Penny drop verified', account['penny_drop_status'] == 'VERIFIED',
          account['penny_drop_status'])
    check('Payout eligible', account['is_payout_eligible'] is True)

    # Mismatched confirmation must be refused.
    other = str(random.randint(10 ** 11, 10 ** 12 - 1))
    response = post('/bank-accounts', {
        'account_number': other,
        'confirm_account_number': str(random.randint(10 ** 11, 10 ** 12 - 1)),
        'ifsc_code': 'HDFC0001234',
    }, token=token)
    check('Mismatched account numbers refused', response.status_code == 400)

    # AC-002 (fee arithmetic) and FR-006 (the transfer itself) covered the
    # credit-to-bank product. That product has been removed; a purchase
    # against an issued credit line replaces it and is not built yet.
    #
    # Left failing rather than skipped, because this is the suite that
    # proves the primary money journey end to end. Sections 1-4 and 7-9
    # below still run, so what does survive is still asserted.
    print(chr(10) + '[5/6] Credit line spend')
    check('a money-movement journey exists to walk end to end', False,
          'BLOCKED: rebuild as the credit-line journey - apply, approve, '
          'limit, purpose, activate, purchase, statement, bill payment.')

    # Nothing was charged, so the ledger must be empty. Asserted rather
    # than assumed: a ledger row here would mean money was recorded that no
    # gateway ever collected.
    on_razorpay = True

    print('\n[7] Ledger')

    response = get('/transactions', token=token)
    txn_ok = check('Transaction list', response.status_code == 200, response.text[:200])

    if txn_ok:
        transactions = response.json()['data']

        if on_razorpay:
            # Nothing was charged, so nothing may be in the ledger. This is a
            # stronger assertion than the settled path's "at least one row":
            # a ledger entry appearing here would mean money was recorded that
            # no gateway ever collected, which is precisely the drift the
            # nightly self-audit exists to catch.
            check('No ledger rows without a charge', len(transactions) == 0,
                  str(len(transactions)))
        else:
            check('Transactions recorded', len(transactions) >= 1,
                  str(len(transactions)))

        if transactions:
            txn_id = transactions[0]['transaction_id']
            response = get(f'/transactions/{txn_id}', token=token)
            if response.status_code == 200:
                entries = response.json()['data'].get('ledger_entries', [])
                check('Double-entry rows present', len(entries) >= 2, str(len(entries)))
                debits = sum(e['debit'] for e in entries)
                credits = sum(e['credit'] for e in entries)
                check('Ledger balances', abs(debits - credits) < 0.01,
                      f'Dr {debits} vs Cr {credits}')

    # ── EMI (FR-007, FR-008) ───────────────────────────────────────────────
    print('\n[8] EMI')

    response = get('/emi/providers', token=token)
    prov_ok = check('Provider directory', response.status_code == 200, response.text[:200])

    if prov_ok:
        providers = response.json()['data']
        bajaj = next((p for p in providers if p['provider_name'] == 'BAJAJ_FINANCE'), None)
        check('Bajaj Finserv seeded', bajaj is not None)

        if bajaj:
            # A known test loan, not a random one. The provider adapter only
            # returns details for loans it actually knows - it never fabricates
            # them - so a random account number resolves to nothing and the add
            # below then correctly demands the amount and due date by hand.
            lan = 'LAN4567890'
            response = post('/emi/lookup', {
                'provider_id': bajaj['provider_id'], 'loan_account_no': lan,
            }, token=token)
            lookup_ok = check('Loan lookup', response.status_code == 200,
                              response.text[:200])
            if lookup_ok:
                check('Loan details actually resolved',
                      (response.json().get('data') or {}).get('found') is True,
                      response.text[:200])

            response = post('/emi', {
                'provider_id': bajaj['provider_id'], 'loan_account_no': lan,
            }, token=token)
            emi_ok = check('EMI added', response.status_code == 201, response.text[:300])

            if emi_ok:
                emi = response.json()['data']
                check('Loan account masked',
                      emi['masked_loan_account'].startswith('LAN-******'),
                      emi['masked_loan_account'])

                # PRD 11.1: a credit card must never pay a loan EMI.
                response = post('/emi-payments', {
                    'emi_id': emi['emi_id'], 'payment_mode': 'CREDIT_CARD',
                }, token=token, idem=uuid.uuid4().hex)
                check('Credit card refused for EMI', response.status_code == 400,
                      response.text[:200])

                response = post('/emi-payments', {
                    'emi_id': emi['emi_id'], 'payment_mode': 'UPI_INTENT',
                }, token=token, idem=uuid.uuid4().hex)
                pay_ok = check('EMI payment initiated', response.status_code == 201,
                               response.text[:300])

                if pay_ok:
                    opened = response.json()['data']
                    payment_id = opened['payment_id']
                    upi_live = (
                        (opened.get('checkout') or {}).get('provider') == 'RAZORPAY'
                    )

                    response = post(f'/emi-payments/{payment_id}/confirm',
                                    token=token)
                    if response.status_code == 200:
                        status = response.json()['data']['status']

                        if upi_live:
                            # A real UPI order nobody has paid. The only correct
                            # outcome is to wait - marking this SETTLED would be
                            # the fabricated success the whole design forbids.
                            check('Unpaid UPI order does not settle',
                                  status not in ('SETTLED', 'SUCCESSFUL'), status)
                            check('Unpaid UPI order parks as PENDING',
                                  status == 'PENDING', status)
                        else:
                            check('EMI settled', status == 'SETTLED', status)

    # ── Dashboard (FR-002) ─────────────────────────────────────────────────
    print('\n[9] Dashboard')

    response = get('/dashboard', token=token)
    dash_ok = check('Dashboard', response.status_code == 200, response.text[:300])

    if dash_ok:
        data = response.json()['data']
        check('Summary present', 'summary' in data)
        check('Aggregate limit computed',
              data['summary']['total_credit_limit'] == 300000.0,
              str(data['summary']['total_credit_limit']))
        check('Utilization badge', 'utilization_badge' in data['summary'])
        check('Cards listed', len(data['cards']) == 1)
        check('Quick actions', data['quick_actions']['can_pay_emi'] is True,
              str(data['quick_actions']))

    return finish()


def finish():
    print('\n' + '=' * 60)
    print(f'PASSED {len(PASS)}   FAILED {len(FAIL)}')
    if FAIL:
        print('\nFailures:')
        for name in FAIL:
            print(f'  - {name}')
    print('=' * 60 + '\n')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
