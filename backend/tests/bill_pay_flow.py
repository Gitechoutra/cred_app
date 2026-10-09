"""
Pay Bills, walked end to end against a live backend.

    KYC -> credit line -> verified bank -> eligibility -> quote -> request
    -> OTP -> draw -> payout -> SUCCEEDED | PENDING | FAILED | REVERSED -> History

The refusals matter most. Each one is a way credit could reach a bank account
without the controls the feature exists to enforce:

    - no consent, no OTP, a wrong OTP, a replayed OTP
    - an unverified or someone else's bank account
    - a purpose that does not match the bill, "Other" without a description
    - more than available credit, above the per-bill maximum, above the full-KYC
      threshold for a minimum-KYC holder, past the daily request count
    - a client-supplied fee or total being honoured

And every outcome that is not a success must give the whole draw back - fee
and GST included - which is asserted against the account invariant and the
exact available credit, not just "it went up".

    python tests/bill_pay_flow.py
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from credit_apply import apply_for_credit, link_bank  # noqa: E402
from credit_lifecycle import (  # noqa: E402
    FAIL, PASS, admin_token, approve_kyc, assert_invariant, check, data_of,
    error_of, get, make_user, post, submit_kyc,
)


def finish():
    print('\n' + '=' * 66)
    print(f'  {len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'    FAIL: {label}')
    sys.exit(1 if FAIL else 0)


def available(token):
    return data_of(get('/credit/account', token)).get('available_credit')


def reset_otp_limits():
    """
    The platform allows 3 OTPs per phone per 15 minutes, shared with login. A
    suite that makes a dozen payments in a minute exhausts that by design, so
    the counters are cleared before each OTP with the same development-only
    script the other suites run between runs (it refuses outside DEV).
    """
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, os.path.join(here, 'reset_throttles.py')],
                   capture_output=True, check=False)


def request_bill(token, bank_id, amount='1000', key=None, **over):
    reset_otp_limits()
    body = {
        'category': 'ELECTRICITY', 'provider': 'Tata Power',
        'bill_reference': 'EB-2026-0912', 'purpose': 'ELECTRICITY',
        'amount': amount, 'bank_account_id': bank_id, 'consent': True,
    }
    body.update(over)
    return post('/bill-payments', body, token=token, idem=key or uuid.uuid4().hex)


def pay(token, bank_id, amount='1000', outcome=None, **over):
    """Request, then confirm with the debug OTP. Returns (create, confirm)."""
    created = request_bill(token, bank_id, amount, **over)
    data = data_of(created)
    bill = data.get('bill_payment') or {}
    code = (data.get('otp') or {}).get('debug_otp')
    if not bill or not code:
        return created, None
    body = {'otp': code}
    if outcome:
        body['sandbox_outcome'] = outcome
    return created, post(f'/bill-payments/{bill["bill_payment_id"]}/confirm', body, token=token)


def main():
    print('\nPay Bills\n' + '=' * 66)

    admin = admin_token()
    if not check('administrator login', bool(admin)):
        return finish()

    # ── 1. Blockers before anything exists ───────────────────────────────
    print('\n[1] Eligibility gates')
    _, token = make_user('Bill Payer')
    if not check('signed in', bool(token)):
        return finish()

    state = data_of(get('/bill-payments/eligibility', token))
    codes = [b['code'] for b in state.get('blockers', [])]
    check('not eligible without KYC, credit line or bank', state.get('eligible') is False)
    check('KYC is the first blocker', codes[:1] == ['KYC_REQUIRED'], str(codes))
    check('no credit line is reported', 'NO_CREDIT_LINE' in codes, str(codes))
    check('no verified bank is reported', 'NO_VERIFIED_BANK' in codes, str(codes))
    check('eleven bill categories are offered', len(state.get('categories', [])) == 11)
    check('nine purposes are offered', len(state.get('purposes', [])) == 9)
    check('the consent sentence comes from the server',
          'genuine eligible expense' in (state.get('consent_text') or ''))

    response = request_bill(token, 'nope')
    check('a request before KYC is refused', response.status_code == 403,
          f'{response.status_code} {response.text[:160]}')

    # ── 2. A credit line and a verified bank ─────────────────────────────
    print('\n[2] Setting up the holder')
    submit_kyc(token, 'Bill Payer', tier='MINIMUM')
    response = apply_for_credit(post, token, {
        'employment_type': 'SALARIED', 'monthly_income': 60000,
        'existing_emi_outflow': 0, 'bureau_consent': True,
    })
    application_id = (data_of(response).get('application') or data_of(response)).get('application_id')
    if not check('credit application submitted', bool(application_id),
                 f'{response.status_code} {response.text[:200]}'):
        return finish()
    if not check('KYC approved (minimum tier)',
                 approve_kyc(token, admin, 'Bill Payer', tier='MINIMUM')):
        return finish()
    response = post(f'/admin/credit/applications/{application_id}/review',
                    {'decision': 'APPROVE'}, token=admin)
    if not check('credit line approved', response.status_code == 200,
                 f'{response.status_code} {response.text[:200]}'):
        return finish()

    state = data_of(get('/bill-payments/eligibility', token))
    codes = [b['code'] for b in state.get('blockers', [])]
    check('an inactive credit line blocks Pay Bills', 'CREDIT_NOT_ACTIVE' in codes, str(codes))

    post('/credit/account/purpose', {'purpose': 'BILLS'}, token=token)
    response = post('/credit/account/activate', token=token)
    if not check('credit line activated', response.status_code == 200, response.text[:200]):
        return finish()

    state = data_of(get('/bill-payments/eligibility', token))
    check('eligible once KYC, an active line and a verified bank exist',
          state.get('eligible') is True, str(state.get('blockers')))
    banks = state.get('banks') or []
    if not check('the salary account is offered as verified', len(banks) >= 1):
        return finish()
    bank_id = banks[0]['bank_account_id']
    check('bank is shown masked, never in full',
          '4' not in (banks[0].get('masked_account') or '')[:4]
          and len(banks[0].get('account_last4') or '') == 4)
    limit, start = state['credit_limit'], state['available_credit']
    check('credit limit and available credit are reported', limit > 0 and start == limit,
          f'{start}/{limit}')
    check('amount for bills is capped at the minimum-KYC threshold',
          state['available_for_bills'] <= 10000, str(state['available_for_bills']))
    check('masked mobile only', '*' in (state.get('masked_mobile') or ''))

    # ── 3. Pricing ───────────────────────────────────────────────────────
    print('\n[3] Fee and GST disclosure')
    quote = data_of(post('/bill-payments/quote', {'amount': '10000'}, token=token))
    check('fee is 1.5% of the bill', quote.get('fee') == 150.0, str(quote))
    check('GST is 18% of the fee, never of the bill', quote.get('gst') == 27.0, str(quote))
    check('total = bill + fee + GST', quote.get('total') == 10177.0, str(quote))
    response = post('/bill-payments/quote', {'amount': '1e9'}, token=token)
    check("'1e9' is not an amount", response.status_code == 400)

    # ── 4. Refusals ──────────────────────────────────────────────────────
    print('\n[4] Refusals that keep credit where it is')
    cases = [
        ('without consent', dict(consent=False), 'consent'),
        ('a purpose that does not match the bill', dict(purpose='RENT'), 'purpose'),
        ('"Other" without a description',
         dict(category='OTHER', provider='Society maintenance', purpose='OTHER'), 'purpose_note'),
        ('a provider not on the list', dict(provider='Nobody Power'), 'provider'),
        ('a malformed bill reference', dict(bill_reference='<x>'), 'bill_reference'),
        ('below the minimum', dict(amount='50'), 'amount'),
        ('above the full-KYC threshold on minimum KYC', dict(amount='12000'), 'amount'),
        ('an unknown bank account', dict(bank_account_id=str(uuid.uuid4())), 'bank_account_id'),
    ]
    for label, over, field in cases:
        amount = over.pop('amount', '1000')
        response = request_bill(token, bank_id, amount, **over)
        check(f'refused {label}',
              response.status_code in (400, 403)
              and (error_of(response).get('details') or {}).get('field') == field,
              f'{response.status_code} {response.text[:180]}')

    response = request_bill(token, bank_id, '1000', fee_amount=0, total_amount=1)
    body = data_of(response).get('bill_payment') or {}
    check('a client-sent fee or total is ignored',
          body.get('fee_amount') == 15.0 and body.get('total_amount') == 1017.7, str(body))
    check('nothing is drawn before the OTP', available(token) == start)

    bill_id = body.get('bill_payment_id')
    response = post(f'/bill-payments/{bill_id}/confirm', {'otp': '000000'}, token=token)
    check('a wrong OTP is refused', response.status_code == 400, response.text[:160])
    check('still nothing drawn after a wrong OTP', available(token) == start)
    response = post(f'/bill-payments/{bill_id}/cancel', token=token)
    check('a request can be cancelled before the OTP',
          data_of(response).get('status') == 'CANCELLED', response.text[:160])

    # Someone else's account.
    _, other = make_user('Someone Else')
    other_bank = link_bank(post, other, holder='Someone Else') if other else None
    response = request_bill(token, other_bank or str(uuid.uuid4()))
    check("another holder's bank account is refused", response.status_code in (400, 403),
          response.text[:160])

    # ── 5. Success ───────────────────────────────────────────────────────
    print('\n[5] A successful payment')
    created, confirmed = pay(token, bank_id, '1000')
    otp_info = data_of(created).get('otp') or {}
    check('OTP is sent to a masked mobile', '*' in (otp_info.get('masked_mobile') or ''))
    bill = data_of(confirmed) if confirmed else {}
    check('payment succeeded', bill.get('status') == 'SUCCEEDED', str(bill)[:200])
    check('reference looks like CASHU + 10', (bill.get('reference') or '').startswith('CASHU')
          and len(bill.get('reference') or '') == 15, bill.get('reference'))
    check('the bank UTR is recorded', bool(bill.get('utr')))
    check('credit drawn is bill + fee + GST', available(token) == round(start - 1017.7, 2),
          f'{available(token)} vs {start - 1017.7}')
    assert_invariant(token, 'after a successful payment')
    check('available-after on the receipt matches the account',
          bill.get('available_after') == available(token))

    response = post(f'/bill-payments/{bill["bill_payment_id"]}/confirm',
                    {'otp': '123456'}, token=token)
    check('confirming again does not draw twice',
          available(token) == round(start - 1017.7, 2), response.text[:120])

    history = data_of(get('/transactions?type=CREDIT_BILL_PAY', token))
    rows = history if isinstance(history, list) else history.get('items', [])
    row = next((r for r in rows if r.get('transaction_id') == bill.get('transaction_id')), {})
    check('the payment is in History', bool(row))
    check('History names the bill', (row.get('bill_payment') or {}).get('title') == 'Electricity Bill',
          str(row.get('bill_payment')))
    check('History shows it successful', row.get('status') == 'SUCCEEDED', row.get('status'))
    check('History carries fee and GST separately',
          row.get('fee_amount') == 15.0 and row.get('tax_amount') == 2.7)
    detail = data_of(get(f'/transactions/{bill.get("transaction_id")}', token))
    entries = detail.get('ledger_entries') or []
    check('the ledger posting balances',
          round(sum(e['debit'] for e in entries), 2) == round(sum(e['credit'] for e in entries), 2)
          and len(entries) >= 5, str(len(entries)))

    # ── 6. Failed: the whole draw comes back ─────────────────────────────
    print('\n[6] A payout the bank declines')
    before = available(token)
    _, confirmed = pay(token, bank_id, '2000', outcome='FAIL')
    bill = data_of(confirmed) if confirmed else {}
    check('payment failed', bill.get('status') == 'FAILED', str(bill)[:200])
    check('the reason is given', bool(bill.get('failure_reason')))
    check('credit restored in full, fee and GST included', available(token) == before,
          f'{available(token)} vs {before}')
    assert_invariant(token, 'after a failed payout')

    # ── 7. Pending, then settled by the status check ─────────────────────
    print('\n[7] Pending payouts')
    before = available(token)
    _, confirmed = pay(token, bank_id, '500', outcome='PENDING')
    bill = data_of(confirmed) if confirmed else {}
    check('payment is pending', bill.get('status') == 'PENDING', str(bill)[:200])
    check('credit is held while pending', available(token) == round(before - 508.85, 2),
          f'{available(token)} vs {before - 508.85}')
    settled = data_of(get(f'/bill-payments/{bill.get("bill_payment_id")}', token))
    check('the status check settles it', settled.get('status') == 'SUCCEEDED', settled.get('status'))
    assert_invariant(token, 'after a pending payout settles')

    # ── 8. The daily request count, then late failure and bank return ────
    print('\n[8] Daily limit, late failure and bank return')
    state = data_of(get('/bill-payments/eligibility', token))
    check('no requests left after three today', state.get('requests_left_today') == 0,
          str(state.get('requests_left_today')))
    response = request_bill(token, bank_id, '500')
    check('the daily request limit is enforced',
          error_of(response).get('code') == 'DAILY_REQUESTS_EXHAUSTED',
          f'{response.status_code} {response.text[:160]}')

    # Raise the cap through the real admin setting for the remaining outcomes,
    # and put it back whatever happens.
    import requests
    from credit_lifecycle import BASE, TIMEOUT

    def set_cap(value):
        return requests.patch(
            f'{BASE}/admin/settings/BILL_PAY_MAX_PER_DAY', json={'value': value},
            headers={'Authorization': f'Bearer {admin}', 'X-Device-UUID': 'credit-flow'},
            timeout=TIMEOUT,
        )

    check('admin raised the daily cap', set_cap('10').status_code == 200)
    try:
        before = available(token)
        _, confirmed = pay(token, bank_id, '400', outcome='PENDING_FAIL')
        bill = data_of(confirmed) if confirmed else {}
        check('a pending payout starts pending', bill.get('status') == 'PENDING')
        settled = data_of(get(f'/bill-payments/{bill.get("bill_payment_id")}', token))
        check('a pending payout that fails is marked failed',
              settled.get('status') == 'FAILED', settled.get('status'))
        check('its credit is restored in full', available(token) == before)
        assert_invariant(token, 'after a late payout failure')

        before = available(token)
        _, confirmed = pay(token, bank_id, '300', outcome='REVERSE')
        bill = data_of(confirmed) if confirmed else {}
        check('a returned payout first succeeds', bill.get('status') == 'SUCCEEDED')
        check('credit is drawn while it stands', available(token) < before)
        settled = data_of(get(f'/bill-payments/{bill.get("bill_payment_id")}', token))
        check('the bank return is detected', settled.get('status') == 'REVERSED',
              settled.get('status'))
        check('credit is restored after the return', available(token) == before,
              f'{available(token)} vs {before}')
        assert_invariant(token, 'after a bank return')
        history = data_of(get('/transactions?type=CREDIT_BILL_PAY', token))
        rows = history if isinstance(history, list) else history.get('items', [])
        row = next((r for r in rows if r.get('transaction_id') == bill.get('transaction_id')), {})
        check('History shows the return', row.get('status') == 'REVERSED', row.get('status'))

        listed = data_of(get('/bill-payments', token))
        listed = listed if isinstance(listed, list) else listed.get('items', [])
        check('Pay Bills history lists only authenticated requests',
              all(item.get('otp_verified_at') for item in listed) and len(listed) == 5,
              str(len(listed)))
    finally:
        check('admin restored the daily cap', set_cap('3').status_code == 200)

    print('\n' + '-' * 66)
    return finish()


if __name__ == '__main__':
    main()
