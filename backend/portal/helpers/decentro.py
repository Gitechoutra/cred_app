"""
portal/helpers/decentro.py
==========================
Decentro credit bureau client - a consented, PAN-based credit report pull.

Decentro is an API aggregator with bureau partnerships, so CashU does not need
its own bureau membership to pull a report. One endpoint answers for Experian
(EX), CRIF High Mark (CR) and Equifax (EQ); which ones an account may call is
switched on by Decentro per client. TransUnion CIBIL is NOT offered through this endpoint -
see version1.md for what a CIBIL pull needs.

    POST {base}/v2/financial_services/credit_bureau/credit_report/summary
    headers: client_id, client_secret
    docs:    https://docs.decentro.tech/reference/credit-report

Called over plain `requests`, like cashfree.py, so what leaves the server is in
plain sight. The PAN is sent only in the request body and never logged.

This module only speaks HTTP and maps Decentro's shapes. It does not decide
what a raw score field means - adapters.interpret_bureau_score does that for
every provider, so NH/NA are read the same way everywhere.
"""

import requests
from flask import current_app

_TIMEOUT = 30   # seconds; a bureau answer slower than this is an outage

_BASE_URLS = {
    'STAGING': 'https://in.staging.decentro.tech',
    'PRODUCTION': 'https://in.decentro.tech',
}

_PATH = '/v2/financial_services/credit_bureau/credit_report/summary'

#: Decentro bureau codes and the bureau each one is.
BUREAUS = {'EX': 'EXPERIAN', 'CR': 'CRIF', 'EQ': 'EQUIFAX'}

#: Sent with every pull. Decentro requires more than 20 characters, and the
#: purpose is what the user agreed to on the consent screen.
CONSENT_PURPOSE = ('Fetching the customer\'s own credit score and credit report '
                   'with their explicit consent, to show it to them and to '
                   'assess their credit line application')


def _config() -> dict:
    cfg = current_app.config
    env = (cfg.get('DECENTRO_ENV') or 'STAGING').upper()
    bureau_code = (cfg.get('DECENTRO_BUREAU_CODE') or 'EX').upper()
    return {
        'env': env,
        'base_url': _BASE_URLS.get(env, _BASE_URLS['STAGING']),
        'client_id': cfg.get('DECENTRO_CLIENT_ID', ''),
        'client_secret': cfg.get('DECENTRO_CLIENT_SECRET', ''),
        'bureau_code': bureau_code,
        'inquiry_purpose': (cfg.get('DECENTRO_INQUIRY_PURPOSE') or 'CC').upper(),
    }


def is_configured() -> bool:
    cfg = _config()
    return bool(cfg['client_id'] and cfg['client_secret']
                and cfg['bureau_code'] in BUREAUS)


def is_test_environment() -> bool:
    """Staging answers with Decentro's UAT test files, never a real person's."""
    return _config()['env'] != 'PRODUCTION'


def bureau_name() -> str:
    return BUREAUS.get(_config()['bureau_code'], 'UNKNOWN')


def fetch_report(*, reference_id: str, pan: str, name: str, mobile: str,
                 date_of_birth: str = None, pincode: str = None) -> dict:
    """
    Pull one credit report.

    Returns one of:
        {'ok': True, 'no_hit': False, 'raw_score': '777', 'report': {...},
         'reference': decentroTxnId}
        {'ok': True, 'no_hit': True, 'raw_score': None, 'report': None, ...}
        {'ok': False, 'error_code', 'error'}

    error_code is BUREAU_UNAVAILABLE (timeout, network, Decentro or the bureau
    down), BUREAU_AUTH_FAILED (credentials wrong or the bureau not enabled for
    this account - an operator problem, not the user's), BUREAU_REJECTED (the
    request was refused as invalid) or BUREAU_INVALID_RESPONSE.
    """
    cfg = _config()
    payload = {
        'reference_id': reference_id,
        'consent': True,
        'consent_purpose': CONSENT_PURPOSE,
        'name': (name or '').strip()[:40],
        'mobile': _ten_digit_mobile(mobile),
        'inquiry_purpose': cfg['inquiry_purpose'],
        'document_type': 'PAN',
        'document_id': pan,
        'bureau_code': cfg['bureau_code'],
    }
    if date_of_birth:
        payload['date_of_birth'] = date_of_birth
    if pincode and str(pincode).isdigit() and len(str(pincode)) == 6:
        payload['pincode'] = str(pincode)

    headers = {
        'Content-Type': 'application/json',
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
    }

    try:
        response = requests.post(cfg['base_url'] + _PATH, json=payload,
                                 headers=headers, timeout=_TIMEOUT)
    except requests.Timeout:
        current_app.logger.error(f'[decentro] timeout on {reference_id}')
        return _fail('BUREAU_UNAVAILABLE', 'The credit bureau did not respond in time.')
    except requests.RequestException as exc:
        current_app.logger.error(f'[decentro] network error on {reference_id}: '
                                 f'{type(exc).__name__}')
        return _fail('BUREAU_UNAVAILABLE', 'The credit bureau could not be reached.')

    try:
        body = response.json()
    except ValueError:
        current_app.logger.error(f'[decentro] non-JSON HTTP {response.status_code} '
                                 f'on {reference_id}')
        return _fail('BUREAU_UNAVAILABLE' if response.status_code >= 500
                     else 'BUREAU_INVALID_RESPONSE',
                     'The credit bureau returned an unreadable response.')

    txn = body.get('decentroTxnId')
    message = str(body.get('message') or '')[:200]

    if response.status_code in (401, 403):
        current_app.logger.error(f'[decentro] auth refused ({txn}): {message}')
        return _fail('BUREAU_AUTH_FAILED', 'The credit bureau connection is not '
                     'authorised. Check the Decentro credentials.')

    if body.get('status') != 'SUCCESS':
        current_app.logger.warning(
            f'[decentro] {response.status_code} {body.get("responseCode")} '
            f'{body.get("responseKey")} ({txn}): {message}'
        )
        if response.status_code >= 500 or body.get('responseCode') == 'E00045':
            return _fail('BUREAU_UNAVAILABLE', 'The credit bureau is unavailable '
                         'right now.')
        if 'not enabled' in message.lower():
            return _fail('BUREAU_AUTH_FAILED', message)
        return _fail('BUREAU_REJECTED', message or 'The credit bureau refused the request.')

    entries = (((body.get('data') or {}).get('cCRResponse') or {})
               .get('cIRReportDataLst') or [])
    if not entries:
        return _fail('BUREAU_INVALID_RESPONSE', 'The credit bureau returned no report.')

    entry = entries[0] or {}
    error = entry.get('error')
    if error:
        # errorCode "00" is "Consumer not found in bureau": a no-hit, which is
        # new to credit - not a failure and never a score.
        if str(error.get('errorCode')) == '00':
            return {'ok': True, 'no_hit': True, 'raw_score': None, 'report': None,
                    'reference': txn}
        current_app.logger.warning(f'[decentro] bureau error ({txn}): {error}')
        return _fail('BUREAU_INVALID_RESPONSE',
                     str(error.get('errorDesc') or 'The credit bureau returned an error.')[:200])

    data = entry.get('cIRReportData') or {}
    scores = data.get('scoreDetails') or []
    raw_score = scores[0].get('value') if scores else None
    return {
        'ok': True,
        'no_hit': False,
        'raw_score': raw_score,
        'report': map_report(data),
        'reference': txn,
    }


def map_report(data: dict) -> dict:
    """
    Decentro's cIRReportData onto the report shape the Credit Score screen
    reads (see adapters.fetch_credit_report). Only what the screen shows is
    kept: no addresses, phone numbers, emails or identity numbers are stored.
    """
    accounts = []
    for row in data.get('retailAccountDetails') or []:
        limit = _amount(row.get('creditLimit')) or _amount(row.get('sanctionAmount')) \
            or _amount(row.get('highCredit'))
        accounts.append({
            'type': row.get('accountType') or 'Account',
            'lender': row.get('institution') or 'Unknown lender',
            'status': 'Active' if str(row.get('open')).lower() == 'yes' else 'Closed',
            'opened_on': row.get('dateOpened'),
            'limit': limit,
            'balance': _amount(row.get('balance')) or 0,
            'past_due': _amount(row.get('pastDueAmount')) or 0,
        })

    revolving = [a for a in accounts
                 if 'credit card' in a['type'].lower() and a['status'] == 'Active']
    total_limit = sum(a['limit'] or 0 for a in revolving)
    total_balance = sum(a['balance'] for a in revolving)

    # Payment history from the 48-month grid on each account. "000"/"STD" is a
    # month paid on time; other day-past-due codes are late; "*", "XXX" and
    # blanks are months the lender did not report and are not counted.
    on_time = late = 0
    months = set()
    for row in data.get('retailAccountDetails') or []:
        for month in row.get('history48Months') or []:
            status = str(month.get('paymentStatus') or '').strip().upper()
            if status in ('', '*', 'XXX', 'NEW', 'CLSD'):
                continue
            months.add(month.get('key'))
            if status in ('000', 'STD', '0'):
                on_time += 1
            else:
                late += 1
    reported = on_time + late

    enquiries = [
        {'date': row.get('date'), 'lender': row.get('institution') or 'Unknown',
         'purpose': 'Credit enquiry'}
        for row in data.get('enquiries') or []
    ]

    return {
        'accounts': accounts,
        'utilization': {
            'percent': round(total_balance / total_limit * 100) if total_limit else None,
            'total_limit': total_limit,
            'total_balance': total_balance,
        },
        'payment_history': {
            'on_time_percent': round(on_time / reported * 100, 1) if reported else None,
            'months_reviewed': len(months),
            'late_payments': late,
        },
        'enquiries': enquiries,
    }


def _amount(value):
    try:
        number = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return round(number)


def _ten_digit_mobile(phone: str) -> str:
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    return digits[-10:]


def _fail(code: str, message: str) -> dict:
    return {'ok': False, 'error_code': code, 'error': message}
