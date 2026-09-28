"""
Statements across billing cycles, credit balances and late fees.

The lifecycle suite cuts one statement and stops. Everything that goes wrong
with statements goes wrong on the *second* one, so this suite cuts several,
on future dates, which means driving the engine directly in an app context for
the cut and the fee sweep while everything else goes through the API.

It exists because of three defects, each reproduced before it was fixed:

    1. A paid statement's payment was subtracted twice from the next one. Pay
       an 8,000 bill, spend 5,000, and the next statement read 0.00 due and
       PAID while the account owed 5,000 - and so was never late-fee'd.
    2. A refund after the bill was paid was floored at zero and vanished.
    3. A balance under the 1.00 minimum payment could never be paid off.

    python tests/credit_statement_cycles.py      # server must be up
"""

import os
import sys
import uuid
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import credit_concurrency as cc  # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def main():
    print('\nStatements across cycles\n' + '=' * 66)

    admin = cc.admin_token()
    token = cc.make_user('Cycle Holder')
    account = cc.spendable_account(token, admin, 'Cycle Holder', 20000)
    if not check('active credit line', bool(account), str(account)):
        return finish()
    account_id = account['credit_account_id']

    def buy(amount, merchant='Shop'):
        return cc.post('/credit/purchases',
                       {'amount': amount, 'merchant_name': merchant},
                       token=token, idem=uuid.uuid4().hex)

    def pay(amount):
        opened = cc.post('/credit/payments',
                         {'amount': amount, 'payment_method': 'NETBANKING'},
                         token=token, idem=uuid.uuid4().hex)
        if opened.status_code != 201:
            return opened
        pid = cc.data_of(opened)['transaction']['credit_transaction_id']
        return cc.post(f'/credit/payments/{pid}/verify', token=token)

    def state():
        return cc.data_of(cc.get('/credit/account', token))

    def invariant(label):
        a = state()
        check(f'invariant holds {label}',
              round(a['available_credit'] + a['current_outstanding'], 2)
              == round(a['credit_limit'], 2), str(a))

    methods = cc.data_of(cc.get('/credit/payments/methods', token))
    if not any(m['mode'] == 'NETBANKING' and m['provider'] == 'SANDBOX'
               for m in methods.get('permitted', [])):
        check('needs the simulated payment rail (skipped)', True)
        return finish()

    from app import app
    from portal import db
    from portal.helpers import credit_engine
    from portal.models.credit_accounts import CreditAccounts
    from portal.models.credit_statements import CreditStatements

    def cut(days_ahead):
        with app.app_context():
            acc = db.session.get(CreditAccounts, account_id)
            s = credit_engine.cut_statement(
                acc, as_of=date.today() + timedelta(days=days_ahead),
            )
            return s.statement_id

    def statement(statement_id):
        return cc.data_of(cc.get(f'/credit/statements/{statement_id}', token))

    # ── 1. Pay a statement, keep spending, cut the next one ───────────────
    print('\n[1] The statement after a paid statement')
    buy(8000, 'Cycle One')
    first = cut(0)
    check('first statement bills 8,000',
          statement(first)['closing_balance'] == 8000)
    pay(8000)
    check('first statement is paid', statement(first)['status'] == 'PAID')
    buy(5000, 'Cycle Two')
    second = cut(30)
    s2 = statement(second)
    check('second statement opens at the first one\'s closing balance',
          s2['opening_balance'] == 8000, str(s2['opening_balance']))
    check('the payment is counted once on the second statement',
          s2['total_payments'] == 8000, str(s2['total_payments']))
    check('second statement bills what is actually owed',
          s2['closing_balance'] == 5000 == state()['current_outstanding'],
          f"{s2['closing_balance']} vs owed {state()['current_outstanding']}")
    check('second statement is unpaid, with a minimum due',
          s2['status'] == 'UNPAID' and s2['minimum_due'] == 250,
          f"{s2['status']} {s2['minimum_due']}")
    invariant('after two cycles')

    # ── 2. An unpaid statement carried into the next ─────────────────────
    print('\n[2] Carry forward and late fees')
    with app.app_context():
        st = db.session.get(CreditStatements, second)
        st.due_date = date.today() - timedelta(days=1)
        db.session.commit()
        credit_engine.mark_overdue_and_charge_fees()
        again = credit_engine.mark_overdue_and_charge_fees()
    fees = cc.get('/credit/transactions?type=FEE', token).json().get('data') or []
    check('an overdue statement is charged one late fee', len(fees) == 1, str(len(fees)))
    check('a second sweep charges nothing more', not again or again.get('fees_charged') == 0,
          str(again))
    check('the statement is marked overdue', statement(second)['status'] == 'OVERDUE')
    fee = fees[0]['amount'] if fees else 0

    third = cut(60)
    s2_after, s3 = statement(second), statement(third)
    check('the overdue statement is carried forward, not left owing twice',
          s2_after['status'] == 'CARRIED_FORWARD', s2_after['status'])
    check('the next statement opens with the carried balance',
          s3['opening_balance'] == 5000, str(s3['opening_balance']))
    check('the fee is billed on the next statement',
          s3['total_fees'] == fee and s3['closing_balance'] == 5000 + fee,
          f"{s3['total_fees']} {s3['closing_balance']}")
    # 5% of the new balance, plus the 250 minimum that was missed.
    expected_min = round((5000 + fee) * 0.05 + 250, 2)
    check('the missed minimum is added to the new minimum due',
          s3['minimum_due'] == expected_min, f"{s3['minimum_due']} vs {expected_min}")
    with app.app_context():
        st = db.session.get(CreditStatements, second)
        st.due_date = date.today() - timedelta(days=5)
        db.session.commit()
        credit_engine.mark_overdue_and_charge_fees()
    fees = cc.get('/credit/transactions?type=FEE', token).json().get('data') or []
    check('a carried-forward statement is never fee\'d again', len(fees) == 1, str(len(fees)))
    invariant('after carry forward and a fee')

    # ── 3. A refund after the bill is paid becomes credit ─────────────────
    print('\n[3] Refund after paying: a credit balance')
    pay(state()['current_outstanding'])
    check('balance cleared', state()['current_outstanding'] == 0)
    bought = cc.data_of(buy(3000, 'Returnable'))['transaction']
    pay(3000)
    response = cc.post(f"/admin/credit/transactions/{bought['credit_transaction_id']}/refund",
                       {'reason': 'Returned after the bill was paid'},
                       token=admin, idem=uuid.uuid4().hex)
    check('refund issued', response.status_code == 200, response.text[:200])
    a = state()
    check('the refund is kept as a credit balance, not lost',
          a['current_outstanding'] == -3000 and a['credit_balance'] == 3000,
          f"outstanding {a['current_outstanding']} credit {a['credit_balance']}")
    check('available credit rises above the limit by the credit',
          a['available_credit'] == a['credit_limit'] + 3000, str(a['available_credit']))
    check('utilisation is zero, never negative', a['utilization_percent'] == 0,
          str(a['utilization_percent']))
    response = cc.post('/credit/payments', {'amount': 100, 'payment_method': 'NETBANKING'},
                       token=token, idem=uuid.uuid4().hex)
    check('there is nothing to pay while in credit', response.status_code == 409,
          str(response.status_code))
    invariant('with a credit balance')

    fourth = cut(90)
    s4 = statement(fourth)
    check('a statement in credit shows a negative closing balance and no minimum',
          s4['closing_balance'] == -3000 and s4['minimum_due'] == 0
          and s4['status'] == 'PAID', f"{s4['closing_balance']} {s4['minimum_due']} {s4['status']}")

    buy(1000, 'Spent From Credit')
    a = state()
    check('the next spend uses the credit first',
          a['current_outstanding'] == -2000 and a['credit_balance'] == 2000, str(a))
    buy(2500, 'Past The Credit')
    check('spending past the credit starts owing again',
          state()['current_outstanding'] == 500, str(state()['current_outstanding']))
    invariant('after spending the credit')

    # ── 4. A balance under the minimum payment ────────────────────────────
    print('\n[4] Clearing a balance smaller than the minimum payment')
    pay('499.50')
    check('0.50 left owing', state()['current_outstanding'] == 0.5)
    response = pay('0.50')
    check('0.50 itself is below the collectable minimum', response.status_code == 400)
    response = pay('1.00')
    check('paying the 1.00 minimum clears it', response.status_code == 200
          and cc.data_of(response)['transaction']['status'] == 'SUCCEEDED', response.text[:200])
    a = state()
    check('the 0.50 over becomes credit, not lost',
          a['current_outstanding'] == -0.5 and a['credit_balance'] == 0.5, str(a))
    response = cc.post('/credit/payments', {'amount': 5, 'payment_method': 'NETBANKING'},
                       token=token, idem=uuid.uuid4().hex)
    check('a real overpayment is still refused', response.status_code == 409,
          str(response.status_code))
    invariant('at the end')

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
