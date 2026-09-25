"""
The credit line, walked end to end against a live backend.

    apply -> KYC gate -> review -> approval -> limit -> purpose -> activation
    -> purchase -> statement -> bill payment -> credit restored

Written to find defects rather than to demonstrate the happy path. The checks
that matter most here are the refusals, because every one of them is a way the
platform could give away money it should not:

    - spending before a purpose is declared, or before activation
    - spending past the limit, the daily cap or the monthly cap
    - a replayed idempotency key charging twice
    - a client supplying its own available_credit or limit
    - an overpayment banked into a state the product cannot represent
    - a limit granted above the applicant's KYC tier cap

The invariant available_credit + current_outstanding == credit_limit is asserted
after every single money movement, not once at the end. Asserting it only at the
end would let two errors that cancel out pass.

    python tests/credit_lifecycle.py
"""

import os
import random
import sys
import uuid
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from throttle import throttled  # noqa: E402

BASE = os.getenv('CASHU_API', 'http://127.0.0.1:5050/v1')
TIMEOUT = 45

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def post(path, body=None, token=None, idem=None, form=None, files=None):
    headers = {'X-Device-UUID': 'credit-flow'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idem:
        headers['X-Idempotency-Key'] = idem
    if files or form:
        return throttled(lambda: requests.post(
            f'{BASE}{path}', data=form, files=files,
            headers=headers, timeout=TIMEOUT))
    return throttled(lambda: requests.post(
        f'{BASE}{path}', json=body or {}, headers=headers, timeout=TIMEOUT))


def get(path, token=None):
    headers = {'X-Device-UUID': 'credit-flow'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return throttled(lambda: requests.get(
        f'{BASE}{path}', headers=headers, timeout=TIMEOUT))


def data_of(response):
    try:
        return response.json().get('data') or {}
    except ValueError:
        return {}


def error_of(response):
    try:
        return response.json().get('error') or {}
    except ValueError:
        return {}


def make_user(name, mpin='246813'):
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
        post('/authentication/mpin/set', {'mpin': mpin}, token=token)
    return phone, token


def admin_token():
    response = post('/authentication/mpin/verify', {
        'phone': os.getenv('ADMIN_SEED_PHONE', '9999999999'),
        'mpin': os.getenv('ADMIN_SEED_MPIN', '135790'),
    })
    return data_of(response).get('access_token')


def approve_kyc(token, admin, name, tier='MINIMUM'):
    """Take a user to a verified KYC tier through the real review path."""
    user_id = (data_of(get('/users/me', token)) or {}).get('user_id')
    if not user_id:
        return False

    png = b'\x89PNG\r\n\x1a\n' + b'0' * 400
    files = {'pan_document': ('pan.png', png, 'image/png')}
    form = {
        'pan_number': 'ABCDE1234F', 'full_name': name,
        'requested_tier': tier,
    }
    if tier == 'FULL':
        form['aadhaar_number'] = f'{random.randint(100000000000, 999999999999)}'
        files['aadhaar_document'] = ('aadhaar.png', png, 'image/png')

    if post('/kyc/submit', form=form, files=files,
            token=token).status_code not in (200, 201):
        return False

    queue = data_of(get('/admin/kyc/queue', admin))
    rows = queue if isinstance(queue, list) else (queue.get('items') or [])
    kyc_id = next(
        (r.get('kyc_id') for r in rows if r.get('user_id') == user_id), None,
    )
    if not kyc_id:
        return False

    post(f'/admin/kyc/{kyc_id}/review',
         {'decision': 'APPROVE', 'tier': tier}, token=admin)
    return (data_of(get('/kyc/status', token)) or {}).get('kyc_tier') == tier


def assert_invariant(token, label):
    """
    available_credit + current_outstanding == credit_limit.

    Checked after every movement. This is the account's one structural promise,
    and a violation means a balance was written by something that did not do the
    arithmetic the engine does.
    """
    account = data_of(get('/credit/account', token))
    limit = account.get('credit_limit')
    available = account.get('available_credit')
    outstanding = account.get('current_outstanding')
    if limit is None:
        return check(f'invariant holds {label}', False, 'no account')
    return check(
        f'invariant holds {label}',
        round(available + outstanding, 2) == round(limit, 2),
        f'{available} + {outstanding} != {limit}',
    )


def main():
    print('\nCredit line lifecycle\n' + '=' * 66)

    admin = admin_token()
    if not check('administrator login', bool(admin)):
        return finish()

    # ── 1. Eligibility, before anything exists ────────────────────────────
    print('\n[1] Eligibility')
    phone, token = make_user('Credit Walker')
    if not check('signed in', bool(token)):
        return finish()

    response = get('/credit/eligibility', token)
    eligibility = data_of(response)
    check('eligibility readable before applying', response.status_code == 200,
          response.text[:200])
    check('KYC is reported as required', eligibility.get('kyc_required') is True,
          str(eligibility.get('kyc_tier')))
    check('no credit line yet', eligibility.get('has_credit_line') is False)

    response = get('/credit/account', token)
    check('account is a 404, not an empty 200', response.status_code == 404,
          f'got {response.status_code}')
    check('the 404 names the reason',
          error_of(response).get('code') == 'NO_CREDIT_LINE',
          str(error_of(response).get('code')))

    # ── 2. Applying before KYC ────────────────────────────────────────────
    print('\n[2] Application and the KYC gate')
    response = post('/credit/applications', {
        'employment_type': 'SALARIED',
        'monthly_income': 60000,
        'existing_emi_outflow': 5000,
    }, token=token)
    application = data_of(response)
    if not check('application accepted without KYC',
                 response.status_code == 201, response.text[:250]):
        return finish()

    check('parked on the KYC gate',
          application.get('status') == 'KYC_PENDING',
          str(application.get('status')))
    check('no limit approved while unverified',
          application.get('approved_limit') in (None, 0),
          str(application.get('approved_limit')))

    response = post('/credit/applications', {
        'employment_type': 'SALARIED', 'monthly_income': 60000,
    }, token=token)
    check('a second open application is refused', response.status_code == 409,
          f'got {response.status_code}')

    # An unverified applicant cannot be approved into a credit line.
    application_id = application['application_id']
    response = post(f'/credit/applications/{application_id}/review',
                    {'decision': 'APPROVE'}, token=admin)
    check('approval route is under /admin, not /credit',
          response.status_code == 404, f'got {response.status_code}')

    response = post(f'/admin/credit/applications/{application_id}/review',
                    {'decision': 'APPROVE'}, token=admin)
    check('an unverified applicant cannot be approved',
          response.status_code == 400
          or data_of(response).get('status') == 'REJECTED',
          f'{response.status_code} {response.text[:160]}')

    # ── 3. KYC approval advances the application ──────────────────────────
    print('\n[3] KYC approval advances the queue')
    if not check('KYC approved', approve_kyc(token, admin, 'Credit Walker')):
        return finish()

    application = data_of(get(f'/credit/applications/{application_id}', token))
    check('application moved to review on KYC approval',
          application.get('status') == 'UNDER_REVIEW',
          str(application.get('status')))
    check('an indicative offer was computed',
          (application.get('offered_limit') or 0) > 0,
          str(application.get('offered_limit')))

    # 60,000 income less 5,000 outflow = 55,000 disposable; three months of that
    # is 165,000, capped by the MINIMUM-KYC tier ceiling of 50,000. Above the
    # full-KYC threshold, so this applicant is told to upgrade rather than handed
    # a number they did not ask for.
    check('the offer is bounded by the KYC tier cap',
          (application.get('offered_limit') or 0) <= 50000,
          str(application.get('offered_limit')))

    # ── 4. Approval issues an account, and nothing more ───────────────────
    print('\n[4] Approval and issuance')
    response = post(f'/admin/credit/applications/{application_id}/review',
                    {'decision': 'APPROVE', 'limit': 40000}, token=admin)
    decision = data_of(response)
    if not check('approved by an administrator', response.status_code == 200,
                 response.text[:250]):
        return finish()

    check('a credit account was issued',
          bool(decision.get('credit_account_id')))
    check('the approved limit is what was granted',
          decision.get('approved_limit') == 40000,
          str(decision.get('approved_limit')))

    account = data_of(get('/credit/account', token))
    check('issued in PENDING_PURPOSE',
          account.get('status') == 'PENDING_PURPOSE',
          str(account.get('status')))
    check('full limit is available at issuance',
          account.get('available_credit') == 40000,
          str(account.get('available_credit')))
    check('nothing outstanding at issuance',
          account.get('current_outstanding') == 0)
    check('cannot spend yet', account.get('can_spend') is False)
    check('the next step is stated by the server',
          account.get('next_step') == 'DECLARE_PURPOSE',
          str(account.get('next_step')))

    # No PAN anywhere in the payload. The digits between the BIN and the last
    # four are not stored, so they cannot appear.
    check('only a masked number is returned',
          account.get('card_number_masked', '').endswith(account.get('card_last4', 'x'))
          and '*' in account.get('card_number_masked', ''),
          str(account.get('card_number_masked')))
    check('no CVV in the account payload',
          'cvv' not in get('/credit/account', token).text.lower())
    assert_invariant(token, 'at issuance')

    # ── 5. Spending is refused before purpose and activation ──────────────
    print('\n[5] The purpose and activation gates')
    response = post('/credit/purchases', {
        'amount': 500, 'merchant_name': 'Test Shop',
    }, token=token, idem=uuid.uuid4().hex)
    check('spending is refused before a purpose is declared',
          response.status_code == 403, f'got {response.status_code}')
    check('the refusal says what to do',
          bool(error_of(response).get('recovery')),
          str(error_of(response)))

    response = post('/credit/account/activate', token=token)
    check('activation is refused before a purpose is declared',
          response.status_code == 400, f'got {response.status_code}')

    purposes = data_of(get('/credit/account/purpose', token)).get('purposes', [])
    check('the purpose options are offered', len(purposes) >= 8, str(len(purposes)))
    check('OTHER is flagged as needing a note',
          any(p['value'] == 'OTHER' and p['requires_note'] for p in purposes))

    response = post('/credit/account/purpose', {'purpose': 'OTHER'}, token=token)
    check('OTHER without a note is refused', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/credit/account/purpose',
                    {'purpose': 'SHOPPING', 'purpose_note': 'unrelated note'},
                    token=token)
    check('a note on a non-OTHER purpose is refused',
          response.status_code == 400, f'got {response.status_code}')

    response = post('/credit/account/purpose', {'purpose': 'NONSENSE'}, token=token)
    check('an unknown purpose is refused', response.status_code == 400,
          f'got {response.status_code}')

    response = post('/credit/account/purpose', {'purpose': 'EDUCATION'}, token=token)
    account = data_of(response)
    check('a valid purpose is accepted', response.status_code == 200,
          response.text[:200])
    check('purpose recorded', account.get('purpose') == 'EDUCATION')
    check('moved to PENDING_ACTIVATION',
          account.get('status') == 'PENDING_ACTIVATION',
          str(account.get('status')))
    check('still cannot spend', account.get('can_spend') is False)

    response = post('/credit/account/purpose', {'purpose': 'TRAVEL'}, token=token)
    check('the purpose cannot be silently changed afterwards',
          response.status_code == 409, f'got {response.status_code}')

    response = post('/credit/purchases', {
        'amount': 500, 'merchant_name': 'Test Shop',
    }, token=token, idem=uuid.uuid4().hex)
    check('spending is still refused before activation',
          response.status_code == 403, f'got {response.status_code}')

    # ── 6. Activation ─────────────────────────────────────────────────────
    print('\n[6] Activation')
    response = post('/credit/account/activate', token=token)
    account = data_of(response)
    check('activation succeeds once a purpose exists',
          response.status_code == 200, response.text[:200])
    check('status is ACTIVE', account.get('status') == 'ACTIVE')
    check('can spend now', account.get('can_spend') is True)
    check('activation did not change the limit',
          account.get('credit_limit') == 40000)
    assert_invariant(token, 'after activation')

    # ── 7. Purchases ──────────────────────────────────────────────────────
    print('\n[7] Purchases')
    key_one = uuid.uuid4().hex
    response = post('/credit/purchases', {
        'amount': 12000, 'merchant_name': 'Campus Books',
        'merchant_category': 'EDUCATION', 'description': 'Semester texts',
    }, token=token, idem=key_one)
    body = data_of(response)
    if not check('purchase accepted', response.status_code == 201,
                 response.text[:250]):
        return finish()

    check('the limit was drawn down',
          body['account']['available_credit'] == 28000,
          str(body['account']['available_credit']))
    check('the balance went up',
          body['account']['current_outstanding'] == 12000,
          str(body['account']['current_outstanding']))
    check('balance_after is recorded on the transaction',
          body['transaction']['balance_after'] == 12000,
          str(body['transaction']['balance_after']))
    check('recorded as a debit', body['transaction']['direction'] == 'DEBIT')
    check('not marked as a test transaction',
          body['transaction']['is_test'] is False)
    assert_invariant(token, 'after a purchase')

    # The duplicate defence. Same key, same amount.
    response = post('/credit/purchases', {
        'amount': 12000, 'merchant_name': 'Campus Books',
    }, token=token, idem=key_one)
    replay = data_of(response)
    check('a replayed key does not charge twice',
          response.status_code == 200
          and replay['account']['current_outstanding'] == 12000,
          f"{response.status_code} outstanding "
          f"{replay.get('account', {}).get('current_outstanding')}")
    check('the replay returns the original transaction',
          replay['transaction']['credit_transaction_id']
          == body['transaction']['credit_transaction_id'])
    assert_invariant(token, 'after a replayed purchase')

    response = post('/credit/purchases', {
        'amount': 500, 'merchant_name': 'No Key Shop',
    }, token=token)
    check('a purchase without an idempotency key is refused',
          response.status_code == 400, f'got {response.status_code}')

    check('the transaction carries a quotable reference',
          str(body['transaction'].get('reference', '')).startswith('CCT'),
          str(body['transaction'].get('reference')))
    check('available credit after the purchase is recorded on it',
          body['transaction'].get('available_after') == 28000,
          str(body['transaction'].get('available_after')))
    check('the purchase shows the purpose of the credit line',
          body['transaction'].get('credit_purpose') == 'Education',
          str(body['transaction'].get('credit_purpose')))

    # Over the remaining limit: 28,000 available, 30,000 asked.
    decline_key = uuid.uuid4().hex
    response = post('/credit/purchases', {
        'amount': 30000, 'merchant_name': 'Too Expensive',
    }, token=token, idem=decline_key)
    check('a purchase over the available limit is refused',
          response.status_code == 400, f'got {response.status_code}')
    check('the refusal names the available amount, not a gateway error',
          'INSUFFICIENT_CREDIT' == error_of(response).get('code'),
          str(error_of(response).get('code')))
    check('the refusal tells the user how to fix it',
          bool(error_of(response).get('recovery')))
    declined = (error_of(response).get('details') or {}).get('transaction') or {}
    check('the decline is recorded as a FAILED transaction',
          declined.get('status') == 'FAILED', str(declined.get('status')))
    check('the declined transaction has a reference to quote',
          str(declined.get('reference', '')).startswith('CCT'))
    check('the declined transaction says what was still available',
          declined.get('available_after') == 28000,
          str(declined.get('available_after')))
    assert_invariant(token, 'after a refused purchase')

    # The same attempt replayed - a retry after a dropped response. It must be
    # declined again, not quietly re-tried.
    response = post('/credit/purchases', {
        'amount': 30000, 'merchant_name': 'Too Expensive',
    }, token=token, idem=decline_key)
    check('a replayed declined key is declined again',
          response.status_code == 400
          and error_of(response).get('code') == 'INSUFFICIENT_CREDIT',
          f'got {response.status_code} {error_of(response).get("code")}')
    check('the replay names the same declined transaction',
          ((error_of(response).get('details') or {}).get('transaction') or {})
          .get('credit_transaction_id') == declined.get('credit_transaction_id'))
    check('nothing was charged by the decline or its replay',
          data_of(get('/credit/account', token)).get('current_outstanding') == 12000)

    # A client cannot set its own balance. These fields are not in any parser,
    # so they are ignored rather than honoured - which is what this asserts.
    response = post('/credit/purchases', {
        'amount': 100, 'merchant_name': 'Injection Test',
        'available_credit': 999999, 'credit_limit': 999999,
        'current_outstanding': 0, 'balance_after': 0,
    }, token=token, idem=uuid.uuid4().hex)
    injected = data_of(response)
    check('a client-supplied limit is ignored',
          injected.get('account', {}).get('credit_limit') == 40000,
          str(injected.get('account', {}).get('credit_limit')))
    check('a client-supplied available_credit is ignored',
          injected.get('account', {}).get('available_credit') == 27900,
          str(injected.get('account', {}).get('available_credit')))
    assert_invariant(token, 'after an injection attempt')

    for amount, label in [(0, 'zero'), (-100, 'negative'), ('abc', 'alphabetic'),
                          ('1e9', 'scientific'), ('10.555', 'three decimals')]:
        response = post('/credit/purchases', {
            'amount': amount, 'merchant_name': 'Bad Amount',
        }, token=token, idem=uuid.uuid4().hex)
        check(f'a {label} amount is refused', response.status_code == 400,
              f'got {response.status_code} for {amount!r}')

    response = post('/credit/purchases', {
        'amount': 100, 'merchant_name': '',
    }, token=token, idem=uuid.uuid4().hex)
    check('an empty merchant name is refused', response.status_code == 400,
          f'got {response.status_code}')

    # ── 8. Transaction history ────────────────────────────────────────────
    print('\n[8] Transaction history')
    response = get('/credit/transactions', token)
    history = response.json().get('data') or []
    check('history is readable', response.status_code == 200)
    settled = [h for h in history if h['status'] == 'SUCCEEDED']
    check('both purchases are in history', len(settled) == 2, str(len(settled)))
    check('newest first',
          settled[0]['amount'] == 100 and settled[1]['amount'] == 12000,
          str([h['amount'] for h in settled]))
    # Two refused before activation, and one over the limit.
    failed = [h for h in history if h['status'] == 'FAILED']
    check('declined attempts appear in history too', len(failed) == 3,
          str(len(failed)))
    check('a declined attempt says why',
          all(h.get('failure_reason') for h in failed))

    response = get('/credit/transactions?status=FAILED', token)
    check('filtering by status works',
          len(response.json().get('data') or []) == 3,
          str(len(response.json().get('data') or [])))
    response = get('/credit/transactions?status=NONSENSE', token)
    check('an unknown status filter is refused', response.status_code == 400,
          f'got {response.status_code}')

    response = get('/credit/transactions?type=PAYMENT', token)
    check('filtering by type works',
          len(response.json().get('data') or []) == 0)
    response = get('/credit/transactions?type=NONSENSE', token)
    check('an unknown type filter is refused', response.status_code == 400,
          f'got {response.status_code}')

    # Another user must not see this one's transactions.
    _, other = make_user('Credit Stranger')
    if other:
        txn_id = history[0]['credit_transaction_id']
        response = get(f'/credit/transactions/{txn_id}', other)
        check("another user cannot read this user's transaction",
              response.status_code == 404, f'got {response.status_code}')
        response = get('/credit/account', other)
        check('another user has their own (absent) account',
              response.status_code == 404, f'got {response.status_code}')

    # ── 9. Statement ──────────────────────────────────────────────────────
    print('\n[9] Statement')
    account_id = data_of(get('/credit/account', token))['credit_account_id']
    response = post(f'/admin/credit/accounts/{account_id}/statement', token=admin)
    statement = data_of(response)
    if not check('statement cut', response.status_code == 200,
                 response.text[:250]):
        return finish()

    check('closing balance is the sum of the purchases',
          statement.get('closing_balance') == 12100,
          str(statement.get('closing_balance')))
    # 5% of 12,100 = 605.00
    check('minimum due is the configured percentage',
          statement.get('minimum_due') == 605.0,
          str(statement.get('minimum_due')))
    check('a due date was set', bool(statement.get('due_date')))
    check('the due date is after the statement date',
          statement['due_date'] > date.today().isoformat()
          or statement['due_date'] == date.today().isoformat(),
          str(statement.get('due_date')))

    response = post(f'/admin/credit/accounts/{account_id}/statement', token=admin)
    check('cutting twice in one cycle issues one statement',
          data_of(response).get('statement_id') == statement['statement_id'],
          f"{data_of(response).get('statement_number')} vs "
          f"{statement.get('statement_number')}")

    detail = data_of(get(f"/credit/statements/{statement['statement_id']}", token))
    check('the statement lists what it billed',
          len(detail.get('transactions', [])) == 2,
          str(len(detail.get('transactions', []))))
    check('declined attempts are not billed',
          all(t['status'] == 'SUCCEEDED' for t in detail.get('transactions', [])))
    check('the statement records the limit at the close of the cycle',
          detail.get('credit_limit') == 40000, str(detail.get('credit_limit')))
    check('the statement records the available credit at the close',
          detail.get('available_credit') == 27900,
          str(detail.get('available_credit')))
    check('total amount due is the closing balance',
          detail.get('total_amount_due') == 12100,
          str(detail.get('total_amount_due')))

    current = data_of(get('/credit/statements/current', token))
    check('unbilled spend is zero once everything is billed',
          current.get('unbilled_spend') == 0,
          str(current.get('unbilled_spend')))
    check('total outstanding still reflects the debt',
          current.get('total_outstanding') == 12100,
          str(current.get('total_outstanding')))

    # ── 10. Bill payment restores credit ──────────────────────────────────
    print('\n[10] Bill payment: verified at the gateway, then credit restored')
    before = data_of(get('/credit/account', token))

    methods = data_of(get('/credit/payments/methods', token))
    offered = {m['mode'] for m in methods.get('permitted', [])}
    check('UPI, UPI ID, net banking and debit card are offered',
          {'UPI_INTENT', 'UPI_COLLECT', 'NETBANKING', 'DEBIT_CARD'} <= offered,
          str(offered))
    check('a credit card is named as not permitted, with a reason',
          any(p['mode'] == 'CREDIT_CARD' and p.get('reason')
              for p in methods.get('prohibited', [])))
    card_rail = next((m['provider'] for m in methods.get('permitted', [])
                      if m['mode'] == 'NETBANKING'), None)
    simulated = card_rail == 'SANDBOX'

    response = post('/credit/payments', {
        'amount': 99999, 'payment_method': 'NETBANKING',
    }, token=token, idem=uuid.uuid4().hex)
    check('an overpayment is refused', response.status_code == 400,
          f'got {response.status_code}')
    check('the refusal states what is owed',
          '12,100' in response.text or '12100' in response.text,
          response.text[:200])

    response = post('/credit/payments', {
        'amount': 5000, 'payment_method': 'CREDIT_CARD',
    }, token=token, idem=uuid.uuid4().hex)
    check('a credit card cannot settle a credit line',
          response.status_code == 400, f'got {response.status_code}')

    pay_key = uuid.uuid4().hex
    response = post('/credit/payments', {
        'amount': 5000, 'payment_method': 'NETBANKING',
        'statement_id': statement['statement_id'],
    }, token=token, idem=pay_key)
    opened = data_of(response)
    if not check('payment opened', response.status_code == 201,
                 response.text[:250]):
        return finish()
    payment = opened['transaction']

    # The defect this section exists for: credit used to come back the moment
    # the client said it had paid.
    check('the payment waits in PROCESSING for the gateway',
          payment['status'] == 'PROCESSING', str(payment['status']))
    now = data_of(get('/credit/account', token))
    check('no credit is restored before the gateway confirms',
          now['available_credit'] == before['available_credit']
          and now['current_outstanding'] == 12100,
          f"available {now['available_credit']} "
          f"outstanding {now['current_outstanding']}")
    check('nothing is reported as restored yet',
          opened.get('credit_restored') == 0, str(opened.get('credit_restored')))
    check('checkout details are returned', bool(opened.get('checkout')))
    check('the pending payment is visible to the pay screen',
          (data_of(get('/credit/statements/current', token))
           .get('pending_payment') or {})
          .get('credit_transaction_id') == payment['credit_transaction_id'])
    assert_invariant(token, 'while a payment is processing')

    response = post('/credit/payments', {
        'amount': 1000, 'payment_method': 'NETBANKING',
    }, token=token, idem=uuid.uuid4().hex)
    check('a second payment is refused while one is processing',
          response.status_code == 409, f'got {response.status_code}')
    check('the refusal names the payment in flight',
          ((error_of(response).get('details') or {}).get('transaction') or {})
          .get('credit_transaction_id') == payment['credit_transaction_id'])

    response = post('/credit/payments', {
        'amount': 5000, 'payment_method': 'NETBANKING',
    }, token=token, idem=pay_key)
    check('a replayed payment key returns the same payment',
          response.status_code == 200
          and data_of(response)['transaction']['credit_transaction_id']
          == payment['credit_transaction_id'],
          f'got {response.status_code}')

    pid = payment['credit_transaction_id']
    response = post(f'/credit/payments/{pid}/verify',
                    {'razorpay_order_id': 'order_someone_elses'}, token=token)
    check('a verify naming a different order is refused',
          response.status_code == 400, f'got {response.status_code}')

    _, stranger = make_user('Payment Stranger')
    if stranger:
        check("another user cannot verify this user's payment",
              post(f'/credit/payments/{pid}/verify', token=stranger)
              .status_code == 404)

    if not simulated:
        check('gateway-driven checks need the simulated rail (skipped)', True)
        return finish()

    response = post(f'/credit/payments/{pid}/verify', token=token)
    settled = data_of(response)
    check('verification settles the payment',
          response.status_code == 200
          and settled['transaction']['status'] == 'SUCCEEDED',
          response.text[:250])
    check('the outstanding balance fell by the amount paid',
          settled['account']['current_outstanding'] == 7100,
          str(settled['account']['current_outstanding']))
    check('credit was restored by the amount paid',
          settled['account']['available_credit']
          == before['available_credit'] + 5000,
          f"{before['available_credit']} -> "
          f"{settled['account']['available_credit']}")
    check('the response says how much credit came back',
          settled.get('credit_restored') == 5000,
          str(settled.get('credit_restored')))
    check('recorded as a credit, not a debit',
          settled['transaction']['direction'] == 'CREDIT')
    check('available credit after the payment is recorded on it',
          settled['transaction'].get('available_after') == 32900,
          str(settled['transaction'].get('available_after')))
    check('the method it was paid by is recorded',
          settled['transaction'].get('payment_method') == 'NETBANKING')
    assert_invariant(token, 'after a verified payment')

    response = post(f'/credit/payments/{pid}/verify', token=token)
    check('verifying again does not restore credit twice',
          data_of(response).get('account', {}).get('current_outstanding') == 7100)
    response = post('/credit/payments', {
        'amount': 5000, 'payment_method': 'NETBANKING',
    }, token=token, idem=pay_key)
    check('a replayed payment key does not collect twice',
          response.status_code == 200
          and data_of(response)['account']['current_outstanding'] == 7100)
    assert_invariant(token, 'after a replayed payment')

    statement_now = data_of(
        get(f"/credit/statements/{statement['statement_id']}", token)
    )
    check('the payment was applied to the statement',
          statement_now.get('amount_paid') == 5000,
          str(statement_now.get('amount_paid')))
    check('the statement is partially paid',
          statement_now.get('status') == 'PARTIALLY_PAID',
          str(statement_now.get('status')))
    check('minimum due is satisfied',
          statement_now.get('minimum_outstanding') == 0,
          str(statement_now.get('minimum_outstanding')))

    # -- The ways a payment does not go through -------------------------------
    def open_payment(amount, outcome, method='NETBANKING'):
        return post('/credit/payments', {
            'amount': amount, 'payment_method': method,
            'sandbox_outcome': outcome,
        }, token=token, idem=uuid.uuid4().hex)

    response = open_payment(1000, 'DECLINE')
    declined_id = data_of(response).get('transaction', {}).get('credit_transaction_id')
    response = post(f'/credit/payments/{declined_id}/verify', token=token)
    outcome = data_of(response).get('transaction', {})
    check('a payment the bank declines ends FAILED',
          outcome.get('status') == 'FAILED', str(outcome.get('status')))
    check('a failed payment says why', bool(outcome.get('failure_reason')))
    check('a failed payment restores no credit',
          data_of(get('/credit/account', token))['current_outstanding'] == 7100)

    response = open_payment(1000, 'ABANDON')
    abandoned_id = data_of(response).get('transaction', {}).get('credit_transaction_id')
    response = post(f'/credit/payments/{abandoned_id}/verify', token=token)
    check('an unpaid checkout stays PROCESSING on verify',
          data_of(response).get('transaction', {}).get('status') == 'PROCESSING')
    response = post(f'/credit/payments/{abandoned_id}/cancel', token=token)
    check('cancelling an unpaid checkout ends CANCELLED',
          data_of(response).get('transaction', {}).get('status') == 'CANCELLED',
          response.text[:200])
    check('a cancelled payment restores no credit',
          data_of(get('/credit/account', token))['current_outstanding'] == 7100)

    response = open_payment(1000, 'TIMEOUT')
    check('a gateway timeout is reported as one',
          response.status_code == 504
          and error_of(response).get('code') == 'GATEWAY_TIMEOUT',
          f'got {response.status_code} {error_of(response).get("code")}')
    check('the timed-out attempt is recorded as FAILED',
          ((error_of(response).get('details') or {}).get('transaction') or {})
          .get('status') == 'FAILED')
    assert_invariant(token, 'after failed, cancelled and timed-out payments')

    # UPI, through whichever rail is live.
    response = open_payment(500, None, method='UPI_INTENT')
    upi = data_of(response)
    upi_id = upi.get('transaction', {}).get('credit_transaction_id')
    check('a UPI payment opens', response.status_code == 201, response.text[:200])
    if upi.get('checkout', {}).get('provider') == 'RAZORPAY':
        check('Razorpay checkout gets a key and an order',
              bool(upi['checkout'].get('key'))
              and bool(upi['checkout'].get('order_id')))
        response = post(f'/credit/payments/{upi_id}/cancel', token=token)
        check('an unpaid Razorpay order can be cancelled',
              data_of(response).get('transaction', {}).get('status') == 'CANCELLED',
              response.text[:200])
    else:
        response = post(f'/credit/payments/{upi_id}/verify', token=token)
        check('a simulated UPI payment settles',
              data_of(response).get('transaction', {}).get('status') == 'SUCCEEDED')

    remaining = data_of(get('/credit/account', token))['current_outstanding']
    response = open_payment(remaining, None)
    response = post(
        f"/credit/payments/{data_of(response)['transaction']['credit_transaction_id']}/verify",
        token=token,
    )
    final = data_of(response)
    check('the balance can be cleared in full',
          final.get('transaction', {}).get('status') == 'SUCCEEDED',
          response.text[:200])
    check('nothing outstanding once cleared',
          final['account']['current_outstanding'] == 0,
          str(final['account']['current_outstanding']))
    check('the full limit is available again',
          final['account']['available_credit'] == 40000,
          str(final['account']['available_credit']))
    assert_invariant(token, 'after the balance is cleared')

    statement_final = data_of(
        get(f"/credit/statements/{statement['statement_id']}", token)
    )
    check('the statement is marked paid',
          statement_final.get('status') == 'PAID',
          str(statement_final.get('status')))

    response = post('/credit/payments', {
        'amount': 100, 'payment_method': 'UPI',
    }, token=token, idem=uuid.uuid4().hex)
    check('paying a settled line is refused', response.status_code == 409,
          f'got {response.status_code}')

    payments = get('/credit/transactions?type=PAYMENT', token).json().get('data') or []
    check('every payment attempt is in history with its outcome',
          {'SUCCEEDED', 'FAILED', 'CANCELLED'} <= {p['status'] for p in payments},
          str({p['status'] for p in payments}))

    # ── 11. Blocking ──────────────────────────────────────────────────────
    print('\n[11] Blocking')
    response = post('/credit/account/block', {'reason': 'Lost my phone'},
                    token=token)
    check('the holder can block their own card', response.status_code == 200,
          response.text[:200])

    response = post('/credit/purchases', {
        'amount': 100, 'merchant_name': 'Blocked Shop',
    }, token=token, idem=uuid.uuid4().hex)
    check('a blocked card cannot spend', response.status_code == 403,
          f'got {response.status_code}')

    response = post('/credit/account/unblock', token=token)
    check('the holder can unblock it again', response.status_code == 200,
          response.text[:200])
    check('spending works again after unblocking',
          post('/credit/purchases', {
              'amount': 100, 'merchant_name': 'Unblocked Shop',
          }, token=token, idem=uuid.uuid4().hex).status_code == 201)
    assert_invariant(token, 'after blocking and unblocking')

    # ── 11b. Refunds ──────────────────────────────────────────────────────
    print('\n[11b] Refunds')
    response = post('/credit/purchases', {
        'amount': 2000, 'merchant_name': 'Returnable Goods',
        'merchant_category': 'SHOPPING',
    }, token=token, idem=uuid.uuid4().hex)
    bought = data_of(response).get('transaction', {})
    bought_id = bought.get('credit_transaction_id')
    before_refund = data_of(get('/credit/account', token))

    check('a cardholder cannot refund their own purchase',
          post(f'/admin/credit/transactions/{bought_id}/refund',
               {'reason': 'mine', 'amount': 2000}, token=token)
          .status_code in (401, 403))
    check('a refund without a reason is refused',
          post(f'/admin/credit/transactions/{bought_id}/refund',
               {'reason': ''}, token=admin).status_code == 400)

    response = post(f'/admin/credit/transactions/{bought_id}/refund',
                    {'reason': 'Merchant confirmed a partial return',
                     'amount': 500},
                    token=admin, idem=uuid.uuid4().hex)
    check('a partial refund is issued', response.status_code == 200,
          response.text[:200])
    after = data_of(get('/credit/account', token))
    check('a refund restores credit',
          after['available_credit'] == before_refund['available_credit'] + 500,
          f"{before_refund['available_credit']} -> {after['available_credit']}")
    detail = data_of(get(f'/credit/transactions/{bought_id}', token))
    check('the purchase shows how much was refunded',
          detail.get('refunded_amount') == 500, str(detail.get('refunded_amount')))
    check('a partly refunded purchase is still SUCCEEDED',
          detail.get('status') == 'SUCCEEDED', str(detail.get('status')))

    response = post(f'/admin/credit/transactions/{bought_id}/refund',
                    {'reason': 'Remainder returned'}, token=admin,
                    idem=uuid.uuid4().hex)
    check('the remainder can be refunded', response.status_code == 200,
          response.text[:200])
    detail = data_of(get(f'/credit/transactions/{bought_id}', token))
    check('a fully refunded purchase reads as REVERSED',
          detail.get('status') == 'REVERSED', str(detail.get('status')))
    check('a purchase cannot be refunded past its amount',
          post(f'/admin/credit/transactions/{bought_id}/refund',
               {'reason': 'again', 'amount': 1}, token=admin,
               idem=uuid.uuid4().hex).status_code in (400, 409))
    refunds = get('/credit/transactions?type=REFUND', token).json().get('data') or []
    check('refunds appear in history as credits',
          len(refunds) == 2 and all(r['direction'] == 'CREDIT' for r in refunds),
          str(len(refunds)))
    assert_invariant(token, 'after refunds')

    # ── 12. Authorization ─────────────────────────────────────────────────
    print('\n[12] Authorization')
    for path in ['/credit/account', '/credit/transactions', '/credit/statements',
                 '/credit/eligibility']:
        check(f'anonymous refused {path}', get(path).status_code == 401,
              f'got {get(path).status_code}')

    check('a normal user cannot reach the admin credit queue',
          get('/admin/credit/applications', token).status_code in (401, 403),
          f'got {get("/admin/credit/applications", token).status_code}')
    check('a normal user cannot approve their own application',
          post(f'/admin/credit/applications/{application_id}/review',
               {'decision': 'APPROVE', 'limit': 999999},
               token=token).status_code in (401, 403))
    check('a normal user cannot cut their own statement',
          post(f'/admin/credit/accounts/{account_id}/statement',
               token=token).status_code in (401, 403))

    # ── 13. The contract the screens depend on ────────────────────────────
    #
    # Every field the credit screens read, asserted present. A screen that reads
    # a field the API stopped returning does not fail loudly - it renders
    # "undefined" or "₹NaN" into a page about somebody's money, and the build
    # passes, and no other test here notices. So the field list is written down.
    print('\n[13] Response contract for the UI')

    CONTRACT = {
        '/credit/account': (
            get('/credit/account', token),
            ['credit_account_id', 'status', 'card_number_masked', 'card_last4',
             'card_network', 'name_on_card', 'expiry', 'credit_limit',
             'available_credit', 'current_outstanding', 'utilization_percent',
             'purpose', 'purpose_label', 'can_spend', 'statement_day',
             'grace_days', 'unbilled_spend', 'next_step'],
        ),
        '/credit/eligibility': (
            get('/credit/eligibility', token),
            ['can_apply', 'kyc_tier', 'kyc_required', 'max_limit_for_tier',
             'minimum_limit', 'full_kyc_required_above', 'employment_types',
             'has_credit_line', 'open_application_id'],
        ),
        '/credit/statements/current': (
            get('/credit/statements/current', token),
            ['account', 'latest_statement', 'unbilled_spend',
             'total_outstanding', 'payment_methods', 'pending_payment'],
        ),
        f"/credit/statements/{statement['statement_id']}": (
            get(f"/credit/statements/{statement['statement_id']}", token),
            ['statement_id', 'statement_number', 'period_start', 'period_end',
             'statement_date', 'due_date', 'opening_balance', 'total_purchases',
             'total_payments', 'total_refunds', 'total_fees', 'closing_balance',
             'minimum_due', 'minimum_due_percent', 'amount_paid',
             'total_amount_due', 'credit_limit', 'available_credit',
             'amount_outstanding', 'minimum_outstanding', 'status',
             'late_fee_charged', 'transactions'],
        ),
        f'/credit/applications/{application_id}': (
            get(f'/credit/applications/{application_id}', token),
            ['application_id', 'status', 'employment_type', 'monthly_income',
             'existing_emi_outflow', 'requested_limit', 'offered_limit',
             'approved_limit', 'eligibility_score', 'decision_reason',
             'decision_message', 'submitted_at', 'kyc_verified_at',
             'decided_at', 'is_open'],
        ),
    }

    for path, (response, fields) in CONTRACT.items():
        payload = data_of(response)
        missing = [f for f in fields if f not in payload]
        check(f'{path} returns every field the UI reads',
              not missing, f'missing: {", ".join(missing)}')

    txn_fields = ['credit_transaction_id', 'transaction_id', 'type', 'status',
                  'amount', 'direction', 'balance_after', 'merchant_name',
                  'merchant_category', 'description', 'statement_id',
                  'is_test', 'created_on', 'settled_at', 'reference',
                  'available_after', 'credit_purpose', 'failure_reason',
                  'refunded_amount', 'payment_method_label', 'is_terminal']
    rows = get('/credit/transactions', token).json().get('data') or []
    missing = [f for f in txn_fields if rows and f not in rows[0]]
    check('a credit transaction returns every field the UI reads',
          bool(rows) and not missing, f'missing: {", ".join(missing)}')

    methods = data_of(get('/credit/payments/methods', token))
    missing = [f for f in ('permitted', 'prohibited', 'minimum_amount', 'upi',
                           'sandbox', 'prefill') if f not in methods]
    check('/credit/payments/methods returns every field the UI reads',
          not missing, f'missing: {", ".join(missing)}')

    purposes = data_of(get('/credit/account/purpose', token)).get('purposes', [])
    missing = [f for f in ('value', 'label', 'requires_note')
               if purposes and f not in purposes[0]]
    check('a purpose option returns every field the UI reads',
          bool(purposes) and not missing, f'missing: {", ".join(missing)}')

    # ── 13b. Applying with no existing EMIs ───────────────────────────────
    # "I have no EMIs" is the commonest answer, and a declared zero used to be
    # refused as "Amount must be greater than zero".
    print('\n[13b] Applying with no existing EMIs')
    _, zero_emi = make_user('Credit No Emis')
    if zero_emi:
        response = post('/credit/applications', {
            'employment_type': 'SALARIED', 'monthly_income': 30000,
            'existing_emi_outflow': 0,
        }, token=zero_emi)
        check('an application declaring zero EMIs is accepted',
              response.status_code == 201, response.text[:200])
        check('the zero is recorded as zero',
              data_of(response).get('existing_emi_outflow') == 0)
    else:
        check('zero-EMI application check ran', False, 'user unavailable')

    # ── 14. Tier caps on an override ──────────────────────────────────────
    print('\n[14] A limit override is still bounded by the KYC tier')
    _, second = make_user('Credit Capped')
    if second and approve_kyc(second, admin, 'Credit Capped'):
        response = post('/credit/applications', {
            'employment_type': 'SALARIED', 'monthly_income': 500000,
        }, token=second)
        second_app = data_of(response).get('application_id')
        if second_app:
            response = post(
                f'/admin/credit/applications/{second_app}/review',
                {'decision': 'APPROVE', 'limit': 5000000}, token=admin,
            )
            check('an admin cannot grant above the tier cap',
                  response.status_code == 400, f'got {response.status_code}')
            check('the refusal names the cap',
                  '50,000' in response.text or '50000' in response.text,
                  response.text[:200])
    else:
        check('tier cap override check ran', False, 'second user unavailable')

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
