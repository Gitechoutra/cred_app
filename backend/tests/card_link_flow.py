"""
Add Card -> validate -> save -> display, against a running server.

Uses an existing test account that is eligible for a card limit (never the
admin or ADMIN_SEED_PHONE / KEEP_PHONES accounts), signs it in by minting a
session in-process, and talks to the API over HTTP like the browser does. The
card it links is deleted again at the end, so the account is left as found.

    python app.py                      # in one terminal
    python tests/card_link_flow.py     # in another
"""

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

import requests  # noqa: E402

BASE = os.getenv('API_BASE', 'http://localhost:5050/v1')
KEEP = {os.getenv('ADMIN_SEED_PHONE', ''), '7287009688', '7287070952'}

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def main():
    from app import app
    from portal import db
    from portal.helpers import card_limit
    from portal.helpers.jwt import issue_tokens
    from portal.models.cards import Cards
    from portal.models.users import Users

    with app.app_context():
        user = next((u for u in Users.query.order_by(Users.created_on.desc()).all()
                     if u.phone not in KEEP and card_limit.assess(u)['eligible']), None)
        if not check('an eligible test account exists', user is not None,
                     'run tests/credit_bureau_flow.py first to create one'):
            return 1
        tokens = issue_tokens(user, device_uuid='card-link-flow')
        db.session.commit()
        access = tokens['access_token'] if isinstance(tokens, dict) else tokens[0]
        expected_limit = float(card_limit.assess(user)['limit'])
        user_id = user.user_id

    headers = {'Authorization': f'Bearer {access}', 'X-Device-UUID': 'card-link-flow'}

    def link(**overrides):
        body = {'bin': '421823', 'last4': last4, 'expiry_month': '12',
                'expiry_year': '2045', 'cardholder_name': 'LINGAM REVANTH',
                'due_day': 10, 'issuer_bank': 'HDFC Bank', 'brand_color': '#004C8F'}
        body.update(overrides)
        body = {k: v for k, v in body.items() if v is not None}
        response = requests.post(f'{BASE}/cards', json=body, headers=headers, timeout=30)
        payload = response.json()
        return response.status_code, payload.get('data') or {}, payload.get('error') or {}

    # A last four this account has not linked, so the run repeats cleanly.
    with app.app_context():
        taken = {c.last4 for c in Cards.query.filter_by(user_id=user_id).all()}
    last4 = next(f'{n:04d}' for n in random.sample(range(1, 10000), 200)
                 if f'{n:04d}' not in taken)
    created = None

    try:
        print('\n[1] Details that are actually wrong get a clear 400, never a 500')
        cases = [
            ('expiry month 23 (the screenshot)', dict(expiry_month='23'),
             'VALIDATION_ERROR', 'Expiry month must be between 01 and 12.'),
            ('an expired card', dict(expiry_month='01', expiry_year='2020'),
             'ERR-009', 'This card has expired.'),
            ('a due day of 45', dict(due_day=45), 'VALIDATION_ERROR', None),
            ('a card number too short', dict(bin='4218'), 'ERR-001', None),
            ('a last four that is not four digits', dict(last4='12a4'), 'ERR-001', None),
            ('an unknown issuer with no bank chosen', dict(issuer_bank=None), 'ERR-001',
             'We could not identify your card issuer. Please check the number and try again.'),
        ]
        for label, overrides, code, message in cases:
            status, _, error = link(**overrides)
            check(f'{label}: 400 {code}',
                  status == 400 and error.get('code') == code
                  and (message is None or error.get('message') == message), (status, error))

        with app.app_context():
            check('none of them saved a card',
                  Cards.query.filter_by(user_id=user_id, last4=last4).count() == 0)

        print('\n[2] A valid dummy card links')
        status, card, error = link()
        check('201 Card linked', status == 201, (status, error))
        created = card.get('card_id')
        check('only the masked number comes back',
              card.get('masked_pan') == f'**** **** **** {last4}' and card.get('last4') == last4,
              card)
        check('network from the BIN, bank as chosen',
              card.get('network') == 'VISA' and card.get('issuer_bank') == 'HDFC Bank', card)
        check('expiry and due day stored', card.get('expiry_month') == '12'
              and card.get('expiry_year') == '2045' and card.get('due_day') == 10, card)
        check('limit worked out by the server from score and salary',
              card.get('card_limit') == expected_limit
              and card.get('available_limit') == expected_limit, card)
        check('active, and not a test-catalogue card',
              card.get('status') == 'ACTIVE' and card.get('is_test_card') is False, card)

        print('\n[3] It is displayed')
        cards = requests.get(f'{BASE}/cards', headers=headers, timeout=30).json()['data']
        check('in the card list', any(c['card_id'] == created for c in cards['cards']))
        detail = requests.get(f'{BASE}/cards/{created}', headers=headers, timeout=30)
        check('and on its own page', detail.status_code == 200
              and detail.json()['data']['last4'] == last4, detail.text[:200])

        print('\n[4] The same card again')
        status, _, error = link()
        check('409 This card is already linked',
              status == 409 and error.get('message') == 'This card is already linked.',
              (status, error))
        with app.app_context():
            check('and no second copy was saved',
                  Cards.query.filter_by(user_id=user_id, last4=last4).count() == 1)
    finally:
        if created:
            with app.app_context():
                Cards.query.filter_by(card_id=created).delete()
                db.session.commit()

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
