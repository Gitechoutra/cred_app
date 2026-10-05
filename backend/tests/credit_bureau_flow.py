"""
The credit bureau result, eligibility and the admin decision, kept apart.

    PAN -> bureau -> actual score / no-history -> eligibility -> admin review
    -> approve / reject -> credit limit

Five scenarios, each a way the platform could invent or inflate credit:

    1. A bureau score is shown exactly as returned, categorised by the
       existing bands, and only an administrator turns it into a limit.
    2. A new-to-credit applicant (NH / NA) gets "Not Available" and the
       separate no-history path - never a number, never "poor".
    3. Completing PAN, bank, KYC and the application never raises a limit.
    4. Nothing is approved or rejected without an administrator.
    5. No hardcoded or default score anywhere: a PAN with no sandbox file, a
       bureau outage or an unreadable answer all leave the score empty, and the
       sandbox refuses to answer in production.

Part A needs no server. Part B runs against one:

    python app.py                       # in one terminal
    python tests/credit_bureau_flow.py  # in another
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

from credit_apply import apply_for_credit, link_bank  # noqa: E402
from credit_lifecycle import (  # noqa: E402
    admin_queue_row, admin_token, approve_kyc, data_of, get, make_user, post,
    submit_kyc,
)

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def detail_of(admin, application_id):
    return data_of(get(f'/admin/credit/applications/{application_id}', admin))


def review(admin, application_id, decision, note=None):
    body = {'decision': decision}
    if note:
        body['note'] = note
    return post(f'/admin/credit/applications/{application_id}/review', body, token=admin)


# ── Part A: the bureau adapter, no server ─────────────────────────────────

def part_a():
    print('\n[A] Reading a bureau response')
    from portal.helpers import adapters

    read = adapters.interpret_bureau_score
    for raw, score in [('680', 680), (' 812 ', 812), (300, 300), ('900', 900)]:
        result = read(raw)
        check(f'{raw!r} is the score {score}',
              result['outcome'] == 'SCORED' and result['score'] == score, str(result))

    for raw, code in [('NA', 'NA'), ('NH', 'NH'), ('No Hit', 'NH'),
                      ('NO_HIT', 'NH'), ('No Credit History', 'NA'),
                      ('na', 'NA'), ('-1', 'NH'), ('000-1', 'NH'), ('3', 'NA')]:
        result = read(raw)
        check(f'{raw!r} is no credit history ({code}), with no score',
              result['outcome'] == 'NO_HISTORY' and result['score'] is None
              and result['code'] == code, str(result))

    for raw in ['0', '299', '901', '', None, 'ERR#', '7.5', '500500']:
        result = read(raw)
        check(f'{raw!r} is not a score and not turned into one',
              result['outcome'] == 'INVALID' and result['score'] is None, str(result))

    print('\n[A] The sandbox bureau')
    from portal import InitApp
    app = InitApp().app()
    with app.app_context():
        app.config['USE_SANDBOX_ADAPTERS'] = True
        app.config['ENV_NAME'] = 'development'

        def ask(pan):
            return adapters.fetch_credit_score(reference='T', pan=pan)

        result = ask('ABCDE0742F')
        check('a test PAN returns its own score', result.get('score') == 742, str(result))
        result = ask('ABCDE1234F')
        check('a PAN with no sandbox file gets no score - there is no default',
              not result.get('ok') and result.get('score') is None, str(result))
        result = ask('ABCDE0000F')
        check('0000 answers NH, with no score',
              result.get('ok') and result.get('no_history')
              and result.get('score') is None and result.get('bureau_code') == 'NH',
              str(result))
        result = ask('ABCDE0001F')
        check('0001 answers NA, with no score',
              result.get('no_history') and result.get('bureau_code') == 'NA', str(result))
        check('0002 is a bureau outage', ask('ABCDE0002F').get('error_code') == 'BUREAU_UNAVAILABLE')
        check('0003 is an unreadable answer, refused',
              ask('ABCDE0003F').get('error_code') == 'BUREAU_INVALID_RESPONSE')

        app.config['ENV_NAME'] = 'production'
        result = ask('ABCDE0780F')
        check('in production the sandbox answers nothing',
              not result.get('ok') and result.get('score') is None, str(result))
        app.config['ENV_NAME'] = 'development'

    print('\n[A] No fabricated score left in the code')
    portal = os.path.join(BACKEND, 'portal')
    offenders = []
    for root, _, files in os.walk(portal):
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.join(root, name)
            text = open(path, encoding='utf-8').read()
            if 'SANDBOX_CREDIT_SCORE' in text or 'eligibility_score' in text:
                offenders.append(os.path.relpath(path, BACKEND))
            # Any score assigned from a literal rather than a bureau answer.
            for match in re.finditer(r'(credit_score|\.score)\s*=\s*(\d+)', text):
                offenders.append(f'{os.path.relpath(path, BACKEND)}: {match.group(0)}')
    check('no default, literal or derived score is assigned anywhere',
          not offenders, ', '.join(offenders))


# ── Part B: end to end ────────────────────────────────────────────────────

def apply_as(admin, name, pan, income, tier='FULL'):
    _, token = make_user(name)
    if not token or not approve_kyc(token, admin, name, tier=tier, pan=pan):
        return token, {}
    response = apply_for_credit(post, token, {
        'employment_type': 'SALARIED', 'monthly_income': income,
        'bureau_consent': True,
    })
    return token, data_of(response)


def scenario_1(admin):
    print('\n[1] Valid credit score')
    token, application = apply_as(admin, 'Bureau Scored', 'ABCDE0712F', 20000)
    app_id = application.get('application_id')
    if not check('application submitted', bool(app_id), str(application)[:200]):
        return

    check('the score shown is exactly the bureau score',
          application.get('credit_score') == 712, str(application.get('credit_score')))
    check('categorised by the existing bands (700-749 Good)',
          application.get('credit_score_band') == 'Good',
          str(application.get('credit_score_band')))
    check('status is SCORED', application.get('credit_status') == 'SCORED')
    check('still under review - a score does not approve anything',
          application.get('status') == 'UNDER_REVIEW' and not application.get('approved_limit'),
          str(application.get('status')))
    # 20,000 disposable x 2 (700-749 band) = 40,000.
    check('eligible limit from income and score only',
          application.get('eligible_limit') == 40000, str(application.get('eligible_limit')))
    check('no credit line exists before review',
          get('/credit/account', token).status_code == 404)

    detail = detail_of(admin, app_id)
    bureau = detail.get('bureau') or {}
    check('the reviewer sees the same bureau score',
          bureau.get('credit_score') == 712 and bureau.get('status') == 'SCORED', str(bureau))
    check('and that it came from the sandbox bureau', bureau.get('is_demo') is True)

    response = review(admin, app_id, 'APPROVE')
    decided = data_of(response)
    check('an administrator approves', response.status_code == 200, response.text[:200])
    check('approval grants exactly the eligible limit',
          decided.get('approved_limit') == 40000, str(decided.get('approved_limit')))


def scenario_2(admin):
    print('\n[2] New to credit')
    for pan, code in [('ABCDE0000F', 'NH'), ('ABCDE0001F', 'NA')]:
        token, application = apply_as(admin, f'Bureau New {code}', pan, 50000)
        app_id = application.get('application_id')
        if not check(f'{code}: application submitted', bool(app_id), str(application)[:200]):
            continue

        check(f'{code}: no score is created',
              application.get('credit_score') is None
              and application.get('credit_score_band') is None, str(application)[:200])
        check(f'{code}: status New to Credit / No Credit History',
              application.get('credit_status') == 'NO_HISTORY'
              and application.get('credit_status_label') == 'New to Credit / No Credit History'
              and application.get('bureau_code') == code, str(application)[:200])
        check(f'{code}: not treated as a low score',
              application.get('assessment_reason') != 'CREDIT_SCORE_TOO_LOW')
        breakdown = application.get('eligibility_breakdown') or {}
        check(f'{code}: the separate no-history rule applies (1x income, Rs. 20,000 cap)',
              breakdown.get('income_multiple') == 1 and breakdown.get('thin_file_cap') == 20000
              and application.get('eligible_limit') == 20000, str(breakdown))
        check(f'{code}: waits for an administrator',
              application.get('status') == 'UNDER_REVIEW' and not application.get('approved_limit'))

        row = admin_queue_row(admin, app_id)
        check(f'{code}: the admin queue shows no number either',
              row.get('credit_score') is None and row.get('credit_status') == 'NO_HISTORY', str(row))

        if code == 'NA':
            response = review(admin, app_id, 'REJECT', 'Test rejection of a new-to-credit applicant')
            check('NA: the administrator can reject', response.status_code == 200, response.text[:200])
        else:
            response = review(admin, app_id, 'APPROVE')
            check('NH: the administrator can approve on the no-history rule',
                  data_of(response).get('approved_limit') == 20000, response.text[:200])

        score = data_of(get('/credit/score', token)).get('score') or {}
        check(f'{code}: the credit score screen shows no number',
              score.get('score') is None and score.get('no_history') is True
              and score.get('status') == 'NO_HISTORY', str(score))


def scenario_3(admin):
    print('\n[3] Completing the form never raises a limit')
    _, token = make_user('Bureau Steps')
    if not check('signed in', bool(token)):
        return

    def no_limit_offered(label):
        eligibility = data_of(get('/credit/eligibility', token))
        kyc = data_of(get('/kyc/status', token))
        offered = [key for key in ('max_limit_for_tier',) if key in eligibility]
        offered += [key for key in ('max_credit_limit',) if key in (kyc.get('capabilities') or {})]
        offered += [f'tier {t.get("tier")}' for t in kyc.get('tiers') or [] if 'max_credit_limit' in t]
        check(f'{label}: no limit offered', not offered, ', '.join(offered))
        check(f'{label}: no credit line', get('/credit/account', token).status_code == 404)

    no_limit_offered('signed up')
    check('PAN submitted for KYC', submit_kyc(token, 'Bureau Steps', tier='FULL', pan='ABCDE0712F'))
    no_limit_offered('after PAN')
    bank = link_bank(post, token, 'Bureau Steps')
    check('bank account verified', bool(bank))
    no_limit_offered('after bank details')

    response = apply_for_credit(post, token, {
        'employment_type': 'SALARIED', 'monthly_income': 20000,
        'bureau_consent': True,
    }, bank_account_id=bank)
    application = data_of(response)
    app_id = application.get('application_id')
    check('application submitted while KYC is in review',
          application.get('status') == 'KYC_PENDING', str(application.get('status')))
    check('no score before KYC is verified, and so no limit',
          application.get('credit_score') is None and application.get('eligible_limit') is None
          and application.get('credit_status') == 'PENDING', str(application)[:200])
    no_limit_offered('after the application')

    check('KYC approved', approve_kyc(token, admin, 'Bureau Steps', tier='FULL', pan='ABCDE0712F'))
    application = data_of(get(f'/credit/applications/{app_id}', token))
    check('KYC moves it to review, not to approval',
          application.get('status') == 'UNDER_REVIEW' and not application.get('approved_limit'))
    first = application.get('eligible_limit')
    check('the eligible limit is income x score band (20,000 x 2)', first == 40000, str(first))

    link_bank(post, token, 'Bureau Steps')
    again = data_of(get(f'/credit/applications/{app_id}', token)).get('eligible_limit')
    check('another bank account does not raise it', again == first, f'{first} -> {again}')
    check('still no credit line', get('/credit/account', token).status_code == 404)


def scenario_4_and_5(admin):
    print('\n[4] The administrator decides')
    for pan, label in [('ABCDE0002F', 'bureau outage'),
                       ('ABCDE0003F', 'unreadable bureau answer'),
                       ('ABCDE4321F', 'PAN with no bureau file')]:
        token, application = apply_as(admin, f'Bureau Down {pan[5:9]}', pan, 40000)
        app_id = application.get('application_id')
        if not check(f'{label}: application kept', bool(app_id), str(application)[:200]):
            continue
        check(f'{label}: score Not Available, status UNAVAILABLE, nothing invented',
              application.get('credit_score') is None
              and application.get('credit_status') == 'UNAVAILABLE'
              and application.get('eligible_limit') is None
              and application.get('assessment_reason') == 'CREDIT_SCORE_UNAVAILABLE',
              str(application)[:240])
        check(f'{label}: not auto-rejected either', application.get('status') == 'UNDER_REVIEW')
        response = review(admin, app_id, 'APPROVE')
        check(f'{label}: cannot be approved without a bureau answer',
              response.status_code == 400, response.text[:200])
        check(f'{label}: and no credit line was issued',
              get('/credit/account', token).status_code == 404)

    _, poor = apply_as(admin, 'Bureau Poor', 'ABCDE0610F', 60000)
    if poor.get('application_id'):
        check('a 610 score is shown as 610 (Poor) and not eligible',
              poor.get('credit_score') == 610 and poor.get('credit_score_band') == 'Poor'
              and poor.get('assessment_reason') == 'CREDIT_SCORE_TOO_LOW', str(poor)[:200])
        check('but it is not rejected until an administrator does it',
              poor.get('status') == 'UNDER_REVIEW' and poor.get('decided_at') is None)


def main():
    print('\nCredit bureau, eligibility and the admin decision\n' + '=' * 66)
    part_a()

    admin = admin_token()
    if check('administrator login', bool(admin)):
        scenario_1(admin)
        scenario_2(admin)
        scenario_3(admin)
        scenario_4_and_5(admin)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
