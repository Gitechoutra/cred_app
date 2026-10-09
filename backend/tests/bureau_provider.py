"""
The credit bureau provider: which one answers, and how a Decentro response is
read. Needs no server and makes no network call - requests.post is replaced
with Decentro's own documented sample responses
(https://docs.decentro.tech/reference/credit-report), so this proves the
mapping, not the credentials. A real staging pull needs DECENTRO_CLIENT_ID and
DECENTRO_CLIENT_SECRET; see version1.md.

    python tests/bureau_provider.py
"""

import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

import requests  # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


# ── Decentro's documented responses ──────────────────────────────────────

def report_body(score='777'):
    return {
        'decentroTxnId': '84A44C4F24B54A409F438E621B037D1F',
        'status': 'SUCCESS', 'responseCode': 'S00000',
        'message': 'Credit Report fetched successfully',
        'data': {'cCRResponse': {'status': '1', 'cIRReportDataLst': [{'cIRReportData': {
            'iDAndContactInfo': {'personalInfo': {'name': {'fullName': 'JOHN DOE'}},
                                 'identityInfo': {'pANId': [{'idNumber': 'AAAAA1111A'}]}},
            'retailAccountDetails': [
                {'institution': 'ICICI BANK LIMITED', 'accountType': 'Credit Card',
                 'balance': '50000', 'pastDueAmount': '0', 'open': 'Yes',
                 'sanctionAmount': '200000', 'dateOpened': '2025-01-01',
                 'history48Months': [
                     {'key': '11-25', 'paymentStatus': '000'},
                     {'key': '10-25', 'paymentStatus': '000'},
                     {'key': '09-25', 'paymentStatus': '030'},
                     {'key': '08-25', 'paymentStatus': '*'},
                 ]},
                {'institution': 'HDFC BANK', 'accountType': 'Personal Loan',
                 'balance': '120000', 'open': 'No', 'sanctionAmount': '300000',
                 'dateOpened': '2022-03-01', 'history48Months': [
                     {'key': '11-25', 'paymentStatus': '000'}]},
            ],
            'scoreDetails': [{'type': 'ERS', 'name': 'ERS4.0', 'value': score}],
            'enquiries': [{'institution': 'ICICI Bank', 'date': '2025-06-01',
                           'requestPurpose': '10', 'amount': '100000'}],
        }}]}},
        'responseKey': 'success_credit_report',
    }


NO_HIT = {
    'decentroTxnId': '5296AAAA', 'status': 'SUCCESS', 'responseCode': 'S00000',
    'message': 'Credit Report fetched successfully',
    'data': {'cCRResponse': {'status': '1', 'cIRReportDataLst': [
        {'error': {'errorCode': '00', 'errorDesc': 'Consumer not found in bureau'}}]}},
}
PROVIDER_DOWN = {
    'decentroTxnId': '4FE659ED', 'status': 'FAILURE', 'responseCode': 'E00045',
    'message': 'Unexpected response received from the underlying data source / '
               'repository. It may be having a downtime.',
    'responseKey': 'error_provider_error',
}
NOT_ENABLED = {
    'decentroTxnId': 'C44C2A55', 'status': 'FAILURE', 'responseCode': 'E00009',
    'message': 'bureau_code CR is not enabled for your account. Please reach out '
               'to Decentro support.', 'responseKey': 'error_bureau_code',
}
BAD_MOBILE = {
    'decentroTxnId': '29A7E561', 'status': 'FAILURE', 'responseCode': 'E00009',
    'message': 'Mobile cannot be null or empty. Hint: mobile (string).',
    'responseKey': 'error_empty_mobile',
}


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def main():
    from portal import InitApp
    from portal.helpers import adapters

    app = InitApp().app()
    app.config.update(BUREAU_PROVIDER='DECENTRO', DECENTRO_ENV='STAGING',
                      DECENTRO_CLIENT_ID='test-id', DECENTRO_CLIENT_SECRET='test-secret',
                      DECENTRO_BUREAU_CODE='EX', DECENTRO_INQUIRY_PURPOSE='CC',
                      ENV_NAME='development')
    kwargs = dict(reference='CASHUCHKTEST0001', pan='ABCDE1234F',
                  full_name='Test User', phone='+919876543210')

    def pull(status, body=None, raises=None):
        sent = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.update(url=url, json=json, headers=headers, timeout=timeout)
            if raises:
                raise raises
            return FakeResponse(status, body)

        with mock.patch('portal.helpers.decentro.requests.post', side_effect=fake_post):
            return adapters.fetch_credit_report(**kwargs), sent

    with app.app_context():
        print('\n[1] Which provider answers')
        check('DECENTRO with credentials is used', adapters.bureau_provider() == 'DECENTRO')
        info = adapters.bureau_info()
        check('it names the bureau (Experian for EX)', info['bureau'] == 'EXPERIAN', info)
        check('staging is flagged as test data', info['is_test'] is True)

        app.config['DECENTRO_CLIENT_SECRET'] = ''
        check('DECENTRO without credentials is NONE, not the sandbox',
              adapters.bureau_provider() == 'NONE')
        result = adapters.fetch_credit_report(**kwargs)
        check('and a pull is refused as not configured',
              result.get('error_code') == 'BUREAU_NOT_CONFIGURED', result)
        app.config['DECENTRO_CLIENT_SECRET'] = 'test-secret'

        app.config.update(BUREAU_PROVIDER='SANDBOX', ENV_NAME='production')
        check('SANDBOX in production is NONE', adapters.bureau_provider() == 'NONE')
        app.config.update(ENV_NAME='development')
        check('SANDBOX in development answers', adapters.bureau_provider() == 'SANDBOX')
        sandbox = adapters.fetch_credit_report(**{**kwargs, 'pan': 'ABCDE0750F'})
        check('a sandbox score is labelled demo and named SANDBOX',
              sandbox.get('score') == 750 and sandbox.get('is_demo') is True
              and sandbox.get('bureau') == 'SANDBOX', sandbox)
        nofile = adapters.fetch_credit_report(**kwargs)
        check('a sandbox PAN with no test file gets no score',
              nofile.get('error_code') == 'BUREAU_NO_SANDBOX_FILE', nofile)
        app.config['BUREAU_PROVIDER'] = 'DECENTRO'

        print('\n[2] The request sent to Decentro')
        result, sent = pull(200, report_body())
        check('staging URL and summary endpoint',
              sent['url'] == 'https://in.staging.decentro.tech/v2/financial_services/'
                             'credit_bureau/credit_report/summary', sent.get('url'))
        check('client_id and client_secret headers',
              sent['headers'].get('client_id') == 'test-id'
              and sent['headers'].get('client_secret') == 'test-secret')
        body = sent['json']
        check('consent is true with a purpose over 20 characters',
              body['consent'] is True and len(body['consent_purpose']) > 20)
        check('PAN goes as the document', body['document_type'] == 'PAN'
              and body['document_id'] == 'ABCDE1234F')
        check('mobile is the 10 digits', body['mobile'] == '9876543210', body['mobile'])
        check('bureau code and inquiry purpose from config',
              body['bureau_code'] == 'EX' and body['inquiry_purpose'] == 'CC')
        check('a timeout is set', sent['timeout'] and sent['timeout'] <= 60)

        print('\n[3] Reading the answers')
        check('the score is exactly what the bureau returned',
              result.get('ok') and result.get('score') == 777, result)
        check('from DECENTRO / EXPERIAN, staging so is_demo',
              result.get('provider') == 'DECENTRO' and result.get('bureau') == 'EXPERIAN'
              and result.get('is_demo') is True)
        check('the reference is Decentro\'s transaction id',
              result.get('reference') == '84A44C4F24B54A409F438E621B037D1F')
        report = result.get('report') or {}
        check('both accounts mapped', len(report.get('accounts', [])) == 2, report)
        check('utilisation from open cards only (50000 of 200000 = 25%)',
              report.get('utilization', {}).get('percent') == 25, report.get('utilization'))
        ph = report.get('payment_history', {})
        check('payment history: 3 on time, 1 late, unreported month skipped',
              ph.get('late_payments') == 1 and ph.get('on_time_percent') == 75.0
              and ph.get('months_reviewed') == 3, ph)
        check('enquiries mapped', len(report.get('enquiries', [])) == 1)
        check('no identity data kept in the report',
              'AAAAA1111A' not in str(report) and 'JOHN DOE' not in str(report))

        app.config['DECENTRO_ENV'] = 'PRODUCTION'
        result, sent = pull(200, report_body('812'))
        check('production URL', sent['url'].startswith('https://in.decentro.tech/'))
        check('a production answer is not demo',
              result.get('is_demo') is False and result.get('score') == 812, result)
        app.config['DECENTRO_ENV'] = 'STAGING'

        result, _ = pull(200, NO_HIT)
        check('consumer not found is new to credit: no score, NH',
              result.get('ok') and result.get('score') is None
              and result.get('no_history') is True and result.get('bureau_code') == 'NH',
              result)

        for raw in ('0', '1000', '', 'ERR'):
            result, _ = pull(200, report_body(raw))
            check(f'score field {raw!r} is never turned into a score',
                  result.get('ok') is False
                  and result.get('error_code') == 'BUREAU_INVALID_RESPONSE', result)

        print('\n[4] Failures')
        cases = [
            ('E00045 provider downtime', dict(status=422, body=PROVIDER_DOWN), 'BUREAU_UNAVAILABLE'),
            ('HTTP 500', dict(status=500, body={'status': 'FAILURE'}), 'BUREAU_UNAVAILABLE'),
            ('bureau not enabled for the account', dict(status=400, body=NOT_ENABLED), 'BUREAU_AUTH_FAILED'),
            ('HTTP 401', dict(status=401, body={'status': 'FAILURE'}), 'BUREAU_AUTH_FAILED'),
            ('invalid request', dict(status=400, body=BAD_MOBILE), 'BUREAU_REJECTED'),
            ('non-JSON 502', dict(status=502, body=ValueError('html')), 'BUREAU_UNAVAILABLE'),
            ('timeout', dict(status=0, raises=requests.Timeout()), 'BUREAU_UNAVAILABLE'),
            ('connection error', dict(status=0, raises=requests.ConnectionError()), 'BUREAU_UNAVAILABLE'),
        ]
        for label, case, expected in cases:
            result, _ = pull(case['status'], case.get('body'), case.get('raises'))
            check(f'{label} -> {expected}, no score',
                  result.get('ok') is False and result.get('error_code') == expected
                  and 'score' not in result, result)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    if FAIL:
        print('\nFAILURES')
        for label in FAIL:
            print(f'  {label}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
