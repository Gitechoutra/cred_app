"""
The Credit Score screen's API, end to end against a running server, on the
sandbox bureau (BUREAU_PROVIDER=SANDBOX, the development default):

    GET  /credit/score         what the screen opens with
    POST /credit/score/check   consent -> bureau -> stored result

Sandbox PANs pick the bureau's answer by their four digits (ABCDE0750F scores
750; 0000 no hit; 0002 outage; 0003 garbled). Every sandbox answer must come
back labelled as test data, and no failure may ever leave a score behind.

    python app.py                            # in one terminal
    python tests/credit_score_check_flow.py  # in another
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

from credit_lifecycle import data_of, get, make_user, post, submit_kyc  # noqa: E402

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


def user_with_pan(name, pan):
    _, token = make_user(name)
    if not token:
        return None
    if not submit_kyc(token, name, pan=pan):
        return None
    return token


def main():
    print('\n[1] Before KYC')
    _, token = make_user('Score NoKyc')
    if not check('user created', bool(token)):
        return 1
    screen = data_of(get('/credit/score', token))
    check('no score yet', screen.get('score') is None, screen)
    check('cannot check without a PAN', screen.get('can_check') is False, screen)
    bureau = screen.get('bureau') or {}
    check('the screen is told who would answer: the sandbox, as test data',
          bureau.get('provider') == 'SANDBOX' and bureau.get('available') is True
          and bureau.get('is_test') is True, bureau)
    check('and that no real bureau is connected', screen.get('bureau_connected') is False)
    response = post('/credit/score/check', {'consent': True}, token=token)
    check('a check without a PAN is refused with KYC_REQUIRED',
          response.status_code == 422 and error_of(response).get('code') == 'KYC_REQUIRED',
          response.text[:200])

    print('\n[2] A scored check')
    token = user_with_pan('Score Seven Fifty', 'ABCDE0750F')
    if not check('user with PAN on file', bool(token)):
        return 1
    check('can check now', data_of(get('/credit/score', token)).get('can_check') is True)

    response = post('/credit/score/check', {'consent': False}, token=token)
    check('no consent, no enquiry', response.status_code == 400, response.text[:200])
    response = post('/credit/score/check', {}, token=token)
    check('consent missing entirely is refused', response.status_code == 400, response.text[:200])

    response = post('/credit/score/check', {'consent': True}, token=token)
    check('the check succeeds', response.status_code == 200, response.text[:300])
    score = data_of(response).get('score') or {}
    check('the score is exactly the bureau\'s 750', score.get('score') == 750, score)
    check('banded by the backend', bool(score.get('band')), score)
    check('labelled as test data from the sandbox',
          score.get('is_demo') is True and score.get('provider') == 'SANDBOX'
          and score.get('bureau') == 'SANDBOX', score)
    report = score.get('report') or {}
    check('with a report in the shape the screen reads',
          {'accounts', 'utilization', 'payment_history', 'enquiries'} <= set(report), report)
    again = data_of(get('/credit/score', token)).get('score') or {}
    check('and it is what the screen loads next time',
          again.get('score') == 750 and again.get('source') == 'CHECK', again)

    print('\n[3] New to credit')
    token = user_with_pan('Score No Hit', 'ABCDE0000F')
    response = post('/credit/score/check', {'consent': True}, token=token)
    score = data_of(response).get('score') or {}
    check('no hit: a successful check with no number',
          response.status_code == 200 and score.get('score') is None
          and score.get('no_history') is True and score.get('band') is None, score)

    print('\n[4] Failures leave no score')
    for pan, code, status in [('ABCDE0002F', 'BUREAU_UNAVAILABLE', 503),
                              ('ABCDE0003F', 'BUREAU_INVALID_RESPONSE', 502),
                              ('ABCDE1234F', 'BUREAU_NO_SANDBOX_FILE', 422)]:
        token = user_with_pan(f'Score {code[:12]}', pan)
        response = post('/credit/score/check', {'consent': True}, token=token)
        error = error_of(response)
        check(f'{pan}: {status} {code}',
              response.status_code == status and error.get('code') == code,
              response.text[:200])
        check(f'{pan}: a message the user can act on, not the bureau\'s wording',
              bool(error.get('message')) and 'decentro' not in error.get('message', '').lower(),
              error)
        check(f'{pan}: still no score on file',
              data_of(get('/credit/score', token)).get('score') is None)

    print('\n[5] Daily limit')
    token = user_with_pan('Score Limit', 'ABCDE0700F')
    # A bureau outage is not the user's fault and is not counted.
    statuses = [post('/credit/score/check', {'consent': True}, token=token).status_code
                for _ in range(3)]
    check('three checks in a day are allowed', statuses == [200, 200, 200], statuses)
    response = post('/credit/score/check', {'consent': True}, token=token)
    check('the fourth is refused with 429 and a clear message',
          response.status_code == 429 and 'times a day' in error_of(response).get('message', ''),
          response.text[:200])

    token = user_with_pan('Score Outage Refund', 'ABCDE0002F')
    statuses = [post('/credit/score/check', {'consent': True}, token=token).status_code
                for _ in range(4)]
    check('bureau outages do not use up the daily checks', statuses == [503] * 4, statuses)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    if FAIL:
        print('\nFAILURES')
        for label in FAIL:
            print(f'  {label}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
