"""
Manual cards, card themes, refresh, bank-linking status and card bills,
against a running server.

    python app.py                          # in one terminal
    python tests/card_dashboard_flow.py    # in another
"""

import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

from credit_lifecycle import BASE, data_of, get, make_user, post  # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def error_of(response):
    try:
        return (response.json() or {}).get('error') or {}
    except ValueError:
        return {}


def call(method, path, token, body=None):
    return requests.request(method, f'{BASE}{path}', json=body, timeout=45, headers={
        'Authorization': f'Bearer {token}', 'X-Device-UUID': 'credit-flow'})


def main():
    _, token = make_user('Cards Owner')
    _, other = make_user('Cards Stranger')
    if not check('two accounts', token and other):
        return 1

    print('\n[1] Adding a card by hand')
    good = {'issuer_bank': 'HDFC Bank', 'issuer_id': 'hdfc', 'nickname': 'Regalia',
            'network': 'VISA', 'last4': '4821', 'credit_limit': '200000',
            'outstanding_balance': '45000.50', 'minimum_due': '2250',
            'total_due': '45000.50', 'payment_due_date': '2026-11-05', 'statement_day': 12}
    bad_cases = [
        ('a full card number', {**good, 'card_number': '4218234567890123'}, 'card_number'),
        ('a CVV', {**good, 'cvv': '123'}, 'cvv'),
        ('an OTP', {**good, 'otp': '123456'}, 'otp'),
        ('a card number hidden in the nickname', {**good, 'nickname': '4218 2345 6789 0123'},
         'nickname'),
        ('three digits for the last four', {**good, 'last4': '482'}, 'last4'),
        ('no bank', {**good, 'issuer_bank': ''}, 'issuer_bank'),
        ('a negative limit', {**good, 'credit_limit': '-5'}, 'credit_limit'),
        ('a zero limit', {**good, 'credit_limit': '0'}, 'credit_limit'),
        ('three decimal places', {**good, 'outstanding_balance': '10.555'}, 'outstanding_balance'),
        ('available above the limit', {**good, 'available_credit': '250000'}, 'available_credit'),
        ('minimum due above total due', {**good, 'minimum_due': '50000'}, 'minimum_due'),
        ('a bad due date', {**good, 'payment_due_date': '05/11/2026'}, 'payment_due_date'),
        ('a statement day of 40', {**good, 'statement_day': 40}, 'statement_day'),
        ('an unknown network', {**good, 'network': 'BITCOIN'}, 'network'),
    ]
    for label, body, field in bad_cases:
        response = call('POST', '/cards/manual', token, body)
        check(f'refused: {label}', response.status_code == 400
              and (error_of(response).get('details') or {}).get('field') == field,
              f'{response.status_code} {error_of(response)}')
    check('nothing was saved by any of them', data_of(get('/cards/manual', token)) in ({}, []))

    response = call('POST', '/cards/manual', token, good)
    card = data_of(response)
    card_id = card.get('manual_card_id')
    check('a valid card is added', response.status_code == 201, response.text[:200])
    check('labelled User-entered - Not Bank Verified',
          card.get('data_source') == 'USER_ENTERED' and card.get('bank_verified') is False
          and card.get('data_source_label') == 'User-entered - Not Bank Verified')
    check('money kept to the paisa', card.get('outstanding_balance') == 45000.5)
    check('available worked out from limit and balance, and flagged as worked out',
          card.get('available_credit') == 154999.5 and card.get('available_is_derived') is True,
          str(card))
    check('utilisation computed', card.get('utilization_percentage') == 22.5, str(card))
    check('only the last four is held', card.get('masked_pan') == '**** **** **** 4821')

    response = call('POST', '/cards/manual', token, {**good, 'issuer_bank': 'hdfc bank'})
    check('the same bank and last four again is a duplicate', response.status_code == 409)
    response = call('POST', '/cards/manual', other, good)
    check('another person may track the same card number',
          response.status_code == 201, response.text[:120])

    print('\n[2] Dashboard')
    listing = data_of(get('/cards', token))
    check('the card list carries manual cards with their own totals',
          len(listing.get('manual_cards', [])) == 1
          and listing.get('manual_totals', {}).get('credit_limit') == 200000)
    check('CashU totals are not mixed with typed-in figures', listing.get('total_limit') == 0)

    print('\n[3] Editing, themes, refresh, removal')
    response = call('PATCH', f'/cards/manual/{card_id}', token,
                    {'outstanding_balance': '60000', 'available_credit': '140000'})
    edited = data_of(response)
    check('figures can be updated', edited.get('outstanding_balance') == 60000
          and edited.get('available_credit') == 140000
          and edited.get('available_is_derived') is False, response.text[:200])
    check('and the change is timestamped', edited.get('last_updated') != card.get('last_updated')
          or edited.get('last_updated'))
    response = call('PATCH', f'/cards/manual/{card_id}', token, {'credit_limit': '100000'})
    check('a limit below the available credit is refused', response.status_code == 400)
    response = call('PATCH', f'/cards/manual/{card_id}', token, {'theme': 'NEON'})
    check('an unknown theme is refused', response.status_code == 400)
    response = call('PATCH', f'/cards/manual/{card_id}', token, {'theme': 'MATTE_BLACK'})
    themed = data_of(response)
    check('a theme is saved', themed.get('theme') == 'MATTE_BLACK')
    check('and changes no figure or status',
          themed.get('outstanding_balance') == 60000 and themed.get('bank_verified') is False
          and themed.get('data_source') == 'USER_ENTERED')
    response = call('POST', f'/cards/manual/{card_id}/refresh', token)
    check('refresh says there is no bank feed, and changes nothing',
          response.status_code == 200 and data_of(response).get('refreshed_from') == 'STORED'
          and data_of(response).get('outstanding_balance') == 60000)

    for method, path in [('GET', f'/cards/manual/{card_id}'),
                         ('PATCH', f'/cards/manual/{card_id}'),
                         ('DELETE', f'/cards/manual/{card_id}')]:
        response = call(method, path, other, {'nickname': 'mine now'})
        check(f'another account cannot {method} it', response.status_code == 404)

    print('\n[4] Bank linking and bills')
    providers = data_of(get('/cards/link/providers', token))
    check('linking reports no provider rather than pretending',
          providers.get('available') is False and providers.get('institutions') == []
          and bool(providers.get('reason')))
    response = call('POST', '/cards/link/sessions', token, {})
    check('no linking session without consent', response.status_code == 400)
    response = call('POST', '/cards/link/sessions', token, {'consent': True})
    check('with consent: 503 provider not configured',
          response.status_code == 503 and error_of(response).get('code') == 'PROVIDER_NOT_CONFIGURED')
    bills = data_of(get('/cards/bills', token)).get('bills', [])
    mine = next((b for b in bills if b['id'] == card_id), {})
    check('the card bill shows what is due', mine.get('minimum_due') == 2250
          and mine.get('due_date') == '2026-11-05', str(mine))
    check('and that it cannot be paid here yet, with why',
          mine.get('pay', {}).get('available') is False and bool(mine.get('pay', {}).get('reason')))

    response = call('DELETE', f'/cards/manual/{card_id}', token)
    check('the card is removed', response.status_code == 200)
    check('and gone from the list', data_of(get('/cards', token)).get('manual_cards') == [])
    check('removing again is not found',
          call('DELETE', f'/cards/manual/{card_id}', token).status_code == 404)
    response = call('POST', '/cards/manual', token, good)
    check('a removed card can be added again', response.status_code == 201)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
