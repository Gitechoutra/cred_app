"""
Submitting a complete credit application, for the credit test suites.

An application is no longer a salary figure: it carries a verified bank account,
an employer and an income proof document, and needs KYC to have been submitted.
Each suite passes its own `post`, so throttling and headers stay its own.
"""

import random

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 400


def link_bank(post, token, holder='Account Holder'):
    """Link and penny-drop verify a bank account. Returns its id, or None."""
    number = str(random.randint(10 ** 11, 10 ** 12 - 1))
    response = post('/bank-accounts', {
        'account_number': number,
        'confirm_account_number': number,
        'ifsc_code': 'HDFC0001234',
        'account_type': 'SAVINGS',
        'account_holder_name': holder,
        'is_primary': True,
    }, token=token)
    try:
        return (response.json().get('data') or {}).get('bank_account_id')
    except ValueError:
        return None


def apply_for_credit(post, token, fields, bank_account_id='auto', proof=True):
    """
    POST /credit/applications as multipart, the way the web form sends it.

    `bank_account_id='auto'` links a fresh verified account first; pass None to
    leave it out. Salaried and self-employed applicants get a default employer
    unless `fields` names one.
    """
    body = dict(fields)
    if body.get('employment_type') in ('SALARIED', 'SELF_EMPLOYED'):
        body.setdefault('employer_name', 'Acme Technologies Pvt Ltd')
        body.setdefault('designation', 'Engineer')
        body.setdefault('months_in_current_job', 24)
    if bank_account_id == 'auto':
        bank_account_id = link_bank(post, token)
    if bank_account_id:
        body['bank_account_id'] = bank_account_id

    form = {
        key: ('true' if value is True else 'false' if value is False else str(value))
        for key, value in body.items() if value is not None
    }
    files = {'income_proof': ('payslip.png', PNG, 'image/png')} if proof else None
    if not files:
        # Still multipart, so the request reads the same as the web form's.
        files = {'unused': ('', b'', 'application/octet-stream')}
    return post('/credit/applications', token=token, form=form, files=files)
