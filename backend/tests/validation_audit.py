"""
A-to-Z validation audit, run against a live backend.

Organised by the section numbers of the validation brief so findings map back
to it directly. Each check states the rule it is enforcing, not just the call
it makes, because a failure here should tell you what is wrong rather than only
that something is.

Bias: this suite is written to *find defects*, not to demonstrate the happy
path. Most checks assert that something invalid is refused. A suite that only
proves valid input works tells you nothing about a payments system.

    python tests/validation_audit.py
"""

import io
import json
import os
import random
import sys
import time
import uuid

import requests

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 45

RESULTS = []   # (section, label, ok, detail)


def check(section, label, ok, detail=''):
    RESULTS.append((section, label, bool(ok), detail))
    print(f'  [{"PASS" if ok else "FAIL"}] {label}'
          + (f' - {detail}' if detail and not ok else ''))
    return bool(ok)


def post(path, body=None, token=None, idem=None, form=None, files=None,
         device='audit'):
    headers = {'X-Device-UUID': device}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem
    if files or form:
        return requests.post(f'{BASE}{path}', data=form, files=files,
                             headers=headers, timeout=TIMEOUT)
    return requests.post(f'{BASE}{path}', json=body or {}, headers=headers,
                         timeout=TIMEOUT)


def get(path, token=None, device='audit'):
    headers = {'X-Device-UUID': device}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return requests.get(f'{BASE}{path}', headers=headers, timeout=TIMEOUT)


def patch(path, body, token):
    headers = {'X-Device-UUID': 'audit',
               'Authorization': f'Bearer {token}'}
    return requests.patch(f'{BASE}{path}', json=body, headers=headers,
                          timeout=TIMEOUT)


def body_of(response):
    try:
        return response.json()
    except ValueError:
        return {}


def data_of(response):
    return body_of(response).get('data') or {}


def make_user(name, mpin):
    """Register a user and return (phone, token) or (phone, None)."""
    phone = f'9{random.randint(100000000, 999999999)}'
    response = post('/authentication/otp/send', {'phone': phone})
    otp = data_of(response).get('debug_otp')
    if not otp:
        return phone, None
    response = post('/authentication/otp/verify', {'phone': phone, 'otp': otp})
    token = data_of(response).get('access_token')
    if token:
        post('/authentication/register',
             {'full_name': name, 'terms_accepted': True}, token=token)
        patch('/users/me',
              {'email': f'{name.lower().replace(" ", ".")}.{phone}@example.com'},
              token)
        post('/authentication/mpin/set', {'mpin': mpin}, token=token)
    return phone, token


# ===========================================================================

def main():
    print('\nCashU validation audit\n' + '=' * 66)

    # -- Users for the ownership tests ------------------------------------
    phone_a, token_a = make_user('Audit Alpha', '246813')
    if not token_a:
        print('Could not register the primary user (rate limited?). Aborting.')
        return report()

    phone_b, token_b = make_user('Audit Beta', '135791')

    # ================= 3. Login validations ==========================
    print('\n[3] Login')

    response = post('/authentication/otp/send', {'phone': ''})
    check(3, 'empty mobile rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/authentication/otp/send', {'phone': '123'})
    check(3, 'short mobile rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/authentication/otp/send', {'phone': '12345abcde'})
    check(3, 'non-numeric mobile rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/authentication/mpin/verify',
                    {'phone': phone_a, 'mpin': '000000'})
    generic = body_of(response).get('error', {}).get('message', '')
    check(3, 'wrong MPIN refused', response.status_code in (400, 401),
          f'got {response.status_code}')
    check(3, 'error does not reveal whether the account exists',
          'not found' not in generic.lower() and 'no user' not in generic.lower()
          and 'does not exist' not in generic.lower(), generic)

    unknown = f'9{random.randint(100000000, 999999999)}'
    response = post('/authentication/mpin/verify',
                    {'phone': unknown, 'mpin': '000000'})
    unknown_msg = body_of(response).get('error', {}).get('message', '')
    check(3, 'unknown account gives the same message as a wrong MPIN',
          unknown_msg == generic, f'{unknown_msg!r} vs {generic!r}')

    response = get('/users/me')
    check(3, 'protected route refuses an anonymous request',
          response.status_code == 401, f'got {response.status_code}')

    response = get('/users/me', token='not-a-real-token')
    check(3, 'protected route refuses a forged token',
          response.status_code in (401, 422), f'got {response.status_code}')

    # ================= 2. OTP validations ============================
    print('\n[2] OTP')

    response = post('/authentication/otp/verify',
                    {'phone': phone_a, 'otp': 'abcdef'})
    check(2, 'non-numeric OTP rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/authentication/otp/verify',
                    {'phone': phone_a, 'otp': '12'})
    check(2, 'short OTP rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/authentication/otp/verify',
                    {'phone': phone_a, 'otp': '999999'})
    check(2, 'wrong OTP rejected', response.status_code in (400, 401),
          f'got {response.status_code}')

    # ================= 18. API shape =================================
    print('\n[18] API contract')

    response = get('/users/me', token=token_a)
    payload = body_of(response)
    check(18, 'success envelope has success+data',
          'success' in payload and 'data' in payload, str(payload)[:120])

    response = post('/authentication/otp/send', {'phone': 'x'})
    payload = body_of(response)
    check(18, 'error envelope has success+error.code+error.message',
          payload.get('success') is False
          and 'code' in (payload.get('error') or {})
          and 'message' in (payload.get('error') or {}), str(payload)[:160])

    # ================= 5. Profile validations ========================
    print('\n[5] Profile')

    response = patch('/users/me', {'full_name': '   '}, token_a)
    check(5, 'whitespace-only name rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = patch('/users/me', {'email': 'not-an-email'}, token_a)
    check(5, 'malformed email rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = patch('/users/me', {'full_name': '  Padded Name  '}, token_a)
    if response.status_code in (200, 201):
        stored = data_of(get('/users/me', token_a)).get('full_name', '')
        check(5, 'name is trimmed before storage', stored == stored.strip(),
              repr(stored))
    else:
        check(5, 'name is trimmed before storage', False,
              f'update refused: {response.status_code}')

    response = patch('/users/me',
                     {'full_name': '<script>alert(1)</script>'}, token_a)
    if response.status_code in (200, 201):
        stored = data_of(get('/users/me', token_a)).get('full_name', '')
        check(17, 'script tags not stored verbatim in a name',
              '<script>' not in stored, repr(stored)[:80])
    else:
        check(17, 'script tags rejected in a name', True)

    # ================= 7. Bank account validations ===================
    print('\n[7] Bank accounts')

    account = f'5010{random.randint(10000000, 99999999)}'

    response = post('/bank-accounts', {
        'account_number': account, 'confirm_account_number': account[:-1] + '9',
        'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
        'account_holder_name': 'Audit Alpha',
    }, token=token_a)
    check(7, 'mismatched confirm account number rejected',
          response.status_code == 400, f'got {response.status_code}')

    response = post('/bank-accounts', {
        'account_number': account, 'confirm_account_number': account,
        'ifsc_code': 'NOTANIFSC', 'account_type': 'SAVINGS',
        'account_holder_name': 'Audit Alpha',
    }, token=token_a)
    check(7, 'malformed IFSC rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/bank-accounts', {
        'account_number': '12', 'confirm_account_number': '12',
        'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
        'account_holder_name': 'Audit Alpha',
    }, token=token_a)
    check(7, 'too-short account number rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/bank-accounts', {
        'account_number': account, 'confirm_account_number': account,
        'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
        'account_holder_name': 'Audit Alpha', 'is_primary': True,
    }, token=token_a)
    bank_a = data_of(response).get('bank_account_id')
    check(7, 'valid bank account accepted', bool(bank_a), response.text[:200])

    if bank_a:
        response = post('/bank-accounts', {
            'account_number': account, 'confirm_account_number': account,
            'ifsc_code': 'HDFC0001234', 'account_type': 'SAVINGS',
            'account_holder_name': 'Audit Alpha',
        }, token=token_a)
        check(7, 'duplicate bank account rejected',
              response.status_code in (400, 409), f'got {response.status_code}')

        listing = get('/bank-accounts', token_a).text
        check(7, 'full account number never returned in a listing',
              account not in listing, 'raw account number present')

    # ================= 6. KYC file validations =======================
    print('\n[6] KYC uploads')

    response = post('/kyc/submit', form={
        'pan_number': 'NOTAPAN', 'full_name': 'Audit Alpha',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('pan.png', b'\x89PNG\r\n\x1a\n' + b'0' * 300,
                               'image/png')}, token=token_a)
    check(6, 'malformed PAN rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F', 'full_name': 'Audit Alpha',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('evil.exe', b'MZ\x90\x00' + b'0' * 300,
                               'application/x-msdownload')}, token=token_a)
    check(6, 'executable upload rejected', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/kyc/submit', form={
        'pan_number': 'ABCDE1234F', 'full_name': 'Audit Alpha',
        'requested_tier': 'MINIMUM',
    }, files={'pan_document': ('big.png', b'\x89PNG\r\n\x1a\n' + b'0' * (11 * 1024 * 1024),
                               'image/png')}, token=token_a)
    check(6, 'oversized upload rejected',
          response.status_code in (400, 413), f'got {response.status_code}')

    # ================= 9 / 26. Amount validations ====================
    print('\n[9/26] Amount validation')

    bad_amounts = [
        ('empty', ''), ('dot', '.'), ('double dot', '..'),
        ('alphabetic', 'abc'), ('special chars', '@@@'),
        ('negative', -100), ('zero', 0),
        ('multiple decimals', '10.5.5'), ('scientific', '1e9'),
        ('three decimals', 10.555), ('huge', 10 ** 12),
        ('null', None),
    ]
    for label, value in bad_amounts:
        response = post('/transfers/quote', {'amount': value}, token=token_a)
        check(9, f'quote rejects {label} amount', response.status_code == 400,
              f'got {response.status_code} for {value!r}')

    response = post('/transfers/quote', {'amount': 5000}, token=token_a)
    check(9, 'quote accepts a valid amount', response.status_code == 200,
          response.text[:160])

    # ================= 8. UPI ID validation ==========================
    print('\n[8] UPI ID')

    # A real EMI, so a 404 cannot mask whether the VPA was ever inspected.
    providers = data_of(get('/emi/providers', token_a)) or []
    provider_id = providers[0].get('provider_id') if providers else None
    emi_id = None
    if provider_id:
        response = post('/emi', {
            'provider_id': provider_id, 'loan_account_no': 'LAN4567890',
        }, token=token_a, idem=uuid.uuid4().hex)
        emi_id = data_of(response).get('emi_id')

    if emi_id:
        for label, vpa in [('no domain', 'mahesh2605'),
                           ('no handle', '@ibl'),
                           ('spaces', 'mahesh 2605@ibl'),
                           ('injection', "'; DROP TABLE users;--@ibl")]:
            response = post('/emi-payments', {
                'emi_id': emi_id, 'payment_mode': 'UPI_COLLECT',
                'upi_vpa': vpa,
            }, token=token_a, idem=uuid.uuid4().hex)
            check(8, f'malformed VPA ({label}) rejected',
                  response.status_code == 400, f'got {response.status_code}')
            # Clean up so the in-flight guard does not mask the next case.
            opened = data_of(response).get('payment_id')
            if opened:
                post(f'/emi-payments/{opened}/cancel', token=token_a)
    else:
        check(8, 'VPA validation checks ran', False, 'no EMI could be created')

    # ================= 17. Ownership / IDOR ==========================
    print('\n[17] Ownership (IDOR)')

    if token_b and bank_a:
        response = get(f'/bank-accounts/{bank_a}', token=token_b)
        check(17, "user B cannot read user A's bank account",
              response.status_code in (403, 404), f'got {response.status_code}')

        response = requests.delete(
            f'{BASE}/bank-accounts/{bank_a}',
            headers={'Authorization': f'Bearer {token_b}',
                     'X-Device-UUID': 'audit'}, timeout=TIMEOUT)
        check(17, "user B cannot delete user A's bank account",
              response.status_code in (403, 404), f'got {response.status_code}')

        response = get(f'/transfers/{uuid.uuid4()}', token=token_b)
        check(17, 'unknown transfer id is a 404, not a leak',
              response.status_code == 404, f'got {response.status_code}')
    else:
        check(17, 'ownership checks ran', False, 'second user unavailable')

    # ================= 20. Admin authorization =======================
    print('\n[20] Admin authorization')

    for path in ['/admin/users', '/admin/kyc/queue', '/admin/transfers',
                 '/admin/settings', '/admin/audit-logs']:
        response = get(path, token=token_a)
        check(20, f'normal user refused {path}',
              response.status_code == 403, f'got {response.status_code}')

        response = get(path)
        check(20, f'anonymous refused {path}',
              response.status_code == 401, f'got {response.status_code}')

    # ================= 14. Transaction history =======================
    print('\n[14] Transaction history')

    response = get('/transactions', token=token_a)
    check(14, 'transaction list responds', response.status_code == 200,
          response.text[:160])

    response = get('/transactions?page=0&per_page=-5', token=token_a)
    check(14, 'invalid pagination handled, not a 500',
          response.status_code in (200, 400), f'got {response.status_code}')

    response = get('/transactions?page=99999', token=token_a)
    check(14, 'page beyond the end is empty, not an error',
          response.status_code == 200, f'got {response.status_code}')

    response = get('/transactions?status=NOT_A_STATUS', token=token_a)
    check(14, 'unknown status filter handled',
          response.status_code in (200, 400), f'got {response.status_code}')

    # ================= 25. Search ====================================
    print('\n[25] Search')

    response = get('/transactions?search=', token=token_a)
    check(25, 'empty search does not error', response.status_code == 200,
          f'got {response.status_code}')

    response = get("/transactions?search=%27%20OR%201%3D1--", token=token_a)
    check(25, 'SQL injection in search does not error or leak',
          response.status_code == 200 and len(data_of(response) or []) == 0,
          f'got {response.status_code}')

    response = get('/transactions?search=%20%20', token=token_a)
    check(25, 'whitespace-only search handled', response.status_code == 200,
          f'got {response.status_code}')

    # ================= 28. Duplicate submission ======================
    print('\n[28] Duplicate protection')

    key = uuid.uuid4().hex
    first = post('/transfers/quote', {'amount': 5000}, token=token_a, idem=key)
    check(28, 'idempotency key accepted on a quote',
          first.status_code in (200, 201), f'got {first.status_code}')

    response = post('/emi-payments', {'emi_id': str(uuid.uuid4()),
                                      'payment_mode': 'UPI_INTENT'},
                    token=token_a)
    check(28, 'payment without an idempotency key refused',
          response.status_code == 400, f'got {response.status_code}')

    # ================= 17. Session invalidation ======================
    print('\n[17] Session lifecycle')

    _, throwaway = make_user('Audit Gamma', '112233')
    if throwaway:
        check(17, 'fresh token works',
              get('/users/me', throwaway).status_code == 200)
        logout = post('/authentication/logout', token=throwaway)
        check(17, 'logout accepted', logout.status_code in (200, 204),
              f'got {logout.status_code}')
        after = get('/users/me', throwaway)
        check(17, 'token rejected after logout', after.status_code == 401,
              f'got {after.status_code}')
    else:
        check(17, 'session lifecycle checks ran', False, 'rate limited')

    # ================= 27. Error handling ============================
    print('\n[27] Error handling')

    response = get('/this-route-does-not-exist', token=token_a)
    check(27, 'unknown route is a clean 404', response.status_code == 404,
          f'got {response.status_code}')

    response = requests.post(
        f'{BASE}/transfers/quote', data='{not json',
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {token_a}',
                 'X-Device-UUID': 'audit'}, timeout=TIMEOUT)
    check(27, 'malformed JSON is a 400, not a 500',
          response.status_code == 400, f'got {response.status_code}')

    check(27, 'no stack traces in error bodies',
          'Traceback' not in response.text, response.text[:120])

    return report()


def report():
    print('\n' + '=' * 66)
    passed = [r for r in RESULTS if r[2]]
    failed = [r for r in RESULTS if not r[2]]
    print(f'{len(passed)} passed, {len(failed)} failed, {len(RESULTS)} total')

    if failed:
        print('\nFAILURES BY SECTION')
        by_section = {}
        for section, label, _, detail in failed:
            by_section.setdefault(section, []).append((label, detail))
        for section in sorted(by_section):
            print(f'\n  Section {section}:')
            for label, detail in by_section[section]:
                print(f'    - {label}' + (f'  ({detail})' if detail else ''))

    out = os.path.join(os.path.dirname(__file__), 'validation_audit_results.json')
    with io.open(out, 'w', encoding='utf-8') as handle:
        json.dump([{'section': s, 'check': c, 'passed': p, 'detail': d}
                   for s, c, p, d in RESULTS], handle, indent=2)
    print(f'\nFull results: {out}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
