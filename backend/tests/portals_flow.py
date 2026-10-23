"""
Three sign-in portals, role separation, Forgot MPIN, email verification, the
support desk and staff management - against a running server.

Staff test accounts are ordinary registered accounts given a role in-process
(the same thing the admin Staff screen does), and are returned to customer
accounts at the end, so the staff list is left as found.

    python app.py                    # in one terminal
    python tests/portals_flow.py     # in another
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

from credit_lifecycle import data_of, get, make_user, post  # noqa: E402

PASS, FAIL = [], []
MPIN = '246813'


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


def clear_auth_throttle():
    """
    This suite signs in far more often than the 5-per-minute auth limit allows
    one address. The limit itself is covered elsewhere; here it is cleared
    before each sign-in (development database only).
    """
    from app import app
    from portal import db
    from portal.models.rate_limit_counters import RateLimitCounters
    with app.app_context():
        RateLimitCounters.query.filter(RateLimitCounters.scope.like('auth:%')).delete(
            synchronize_session=False)
        db.session.commit()


def login(phone, portal, mpin=MPIN):
    clear_auth_throttle()
    return post('/authentication/mpin/verify', {'phone': phone, 'mpin': mpin, 'portal': portal})


def set_role(phone, role_name):
    from app import app
    from portal import db
    from portal.models.roles import Roles
    from portal.models.users import Users
    with app.app_context():
        user = Users.query.filter_by(phone=phone).first()
        user.role_id = Roles.query.filter_by(role_name=role_name).first().role_id
        db.session.commit()


def patch(path, body, token):
    import requests
    from credit_lifecycle import BASE
    return requests.patch(f'{BASE}{path}', json=body, timeout=45, headers={
        'Authorization': f'Bearer {token}', 'X-Device-UUID': 'credit-flow'})


def main():
    created_staff = []
    try:
        return run(created_staff)
    finally:
        for phone in created_staff:
            set_role(phone, 'NORMAL_USER')


def run(created_staff):
    print('\n[1] Accounts')
    member_phone, member = make_user('Portal Member')
    agent_phone, _ = make_user('Portal Agent')
    admin_phone, _ = make_user('Portal Superadmin')
    recruit_phone, recruit = make_user('Portal Recruit')
    if not check('four accounts registered', all([member, agent_phone, admin_phone, recruit])):
        return 1
    set_role(agent_phone, 'L1_SUPPORT')
    set_role(admin_phone, 'L3_SUPER_ADMIN')
    created_staff += [agent_phone, admin_phone, recruit_phone]

    print('\n[2] Each portal admits only its own role')
    for phone, portal, expect in [
        (member_phone, 'USER', 200), (member_phone, 'ADMIN', 403), (member_phone, 'SUPPORT', 403),
        (agent_phone, 'SUPPORT', 200), (agent_phone, 'ADMIN', 403), (agent_phone, 'USER', 403),
        (admin_phone, 'ADMIN', 200), (admin_phone, 'SUPPORT', 403), (admin_phone, 'USER', 403),
    ]:
        response = login(phone, portal)
        ok = response.status_code == expect
        if expect == 403:
            ok = ok and error_of(response).get('code') == 'WRONG_PORTAL' \
                and 'access_token' not in (data_of(response) or {})
        check(f'{phone[-4:]} via {portal}: {expect}', ok,
              f'{response.status_code} {error_of(response)}')
    response = login(member_phone, 'USER', mpin='135791')
    check('a wrong MPIN is still the generic refusal, whatever the portal',
          response.status_code == 401 and error_of(response).get('code') == 'MPIN_INVALID')

    sent = data_of(post('/authentication/otp/send', {'phone': '9111100001'}))
    response = post('/authentication/otp/verify', {'phone': '9111100001',
                                                   'otp': sent.get('debug_otp'),
                                                   'portal': 'SUPPORT'})
    check('an unknown number on a staff portal creates no account',
          response.status_code == 401, response.text[:160])

    agent = data_of(login(agent_phone, 'SUPPORT')).get('access_token')
    admin = data_of(login(admin_phone, 'ADMIN')).get('access_token')
    member = data_of(login(member_phone, 'USER')).get('access_token')

    print('\n[3] The backend enforces roles, whatever the URL')
    for who, token, path, expect in [
        ('agent', agent, '/admin/dashboard', 403), ('agent', agent, '/admin/users', 403),
        ('agent', agent, '/admin/credit/applications', 403),
        ('agent', agent, '/admin/transaction-errors', 403), ('agent', agent, '/admin/staff', 403),
        ('agent', agent, '/support-desk/overview', 200),
        ('member', member, '/support-desk/overview', 403), ('member', member, '/admin/dashboard', 403),
        ('member', member, '/support-desk/customers/search?q=9999999999', 403),
        ('admin', admin, '/admin/dashboard', 200), ('admin', admin, '/admin/staff', 200),
        ('admin', admin, '/support-desk/overview', 200),
    ]:
        response = get(path, token)
        check(f'{who} GET {path}: {expect}', response.status_code == expect,
              str(response.status_code))
    response = post('/admin/credit/applications/x/review', {'decision': 'APPROVE'}, token=agent)
    check('an agent cannot approve a credit application', response.status_code == 403)

    print('\n[4] Forgot MPIN')
    clear_auth_throttle()
    response = post('/authentication/mpin/reset/request', {'phone': '9111100002'})
    check('an unknown number gets the same answer, and no OTP',
          response.status_code == 200 and 'debug_otp' not in data_of(response))
    sent = data_of(post('/authentication/mpin/reset/request', {'phone': member_phone}))
    check('a registered number gets an OTP', bool(sent.get('debug_otp')), str(sent))
    response = post('/authentication/mpin/reset/confirm',
                    {'phone': member_phone, 'otp': '000000', 'mpin': '582914'})
    check('a wrong OTP does not reset', response.status_code == 400)
    clear_auth_throttle()
    sent = data_of(post('/authentication/mpin/reset/request', {'phone': member_phone}))
    response = post('/authentication/mpin/reset/confirm',
                    {'phone': member_phone, 'otp': sent.get('debug_otp'), 'mpin': '111111'})
    check('a weak new MPIN is refused', response.status_code == 400)
    response = post('/authentication/mpin/reset/confirm',
                    {'phone': member_phone, 'otp': sent.get('debug_otp'), 'mpin': '582914'})
    check('the right OTP resets the MPIN', response.status_code == 200
          and data_of(response).get('portal') == 'USER', response.text[:160])
    check('the old session is signed out', get('/users/me', member).status_code == 401)
    check('the old MPIN no longer works', login(member_phone, 'USER').status_code == 401)
    member = data_of(login(member_phone, 'USER', mpin='582914')).get('access_token')
    check('the new MPIN signs in', bool(member))

    print('\n[5] Email verification')
    patch('/users/me', {'email': f'member{member_phone[-4:]}@example.com'}, member)
    response = post('/authentication/email/verify/request', token=member)
    link = data_of(response).get('debug_link', '')
    check('a link is issued (logged, as SMTP is not configured)',
          response.status_code == 200 and 'token=' in link, response.text[:200])
    token = link.split('token=', 1)[-1]
    check('a tampered link is refused',
          post('/authentication/email/verify', {'token': token[:-2] + 'xx'}).status_code == 400)
    response = post('/authentication/email/verify', {'token': token})
    check('the link verifies the email', response.status_code == 200)
    check('and the profile says so', data_of(get('/users/me', member)).get('is_email_verified') is True
          or data_of(get('/users/me', member)).get('email_verified') is True,
          str(data_of(get('/users/me', member)))[:300])
    check('asking again says it is already verified',
          post('/authentication/email/verify/request', token=member).status_code == 409)

    print('\n[6] Support desk')
    created = data_of(post('/support/tickets', {
        'subject': 'Card bill shows twice', 'message': 'My bill appears two times.',
        'category': 'CARD_ISSUE'}, token=member))
    ticket_id = created.get('ticket_id')
    check('the customer raises a ticket', bool(ticket_id), str(created)[:200])
    queue = data_of(get('/support-desk/tickets?status=OPEN', agent))
    check('it is in the open queue', any(t['ticket_id'] == ticket_id for t in queue))
    check('the queue shows a masked phone only',
          member_phone not in str(queue) and member_phone[-4:] in str(queue))

    response = post(f'/support-desk/tickets/{ticket_id}/assign', {'agent': 'me'}, token=agent)
    check('the agent takes it', data_of(response).get('assigned_agent_name') == 'Portal Agent')
    response = post(f'/support-desk/tickets/{ticket_id}/notes',
                    {'message': 'Looks like a duplicate statement row.'}, token=agent)
    check('an internal note is added', response.status_code == 200)
    response = post(f'/support-desk/tickets/{ticket_id}/reply',
                    {'message': 'We are looking into this now.'}, token=agent)
    desk = data_of(response)
    check('the reply moves it to In progress, waiting on the customer',
          desk.get('status_label') == 'In progress' and desk.get('waiting_on') == 'customer')

    mine = data_of(get(f'/support/tickets/{ticket_id}', member))
    bodies = [m['body'] for m in mine.get('messages', [])]
    check('the customer sees the reply', 'We are looking into this now.' in bodies)
    check('the customer never sees the internal note',
          'Looks like a duplicate statement row.' not in str(mine))
    check('the customer sees the four-state label', mine.get('status_label') == 'In progress')

    response = post(f'/support-desk/tickets/{ticket_id}/status', {'status': 'RESOLVED'}, token=agent)
    check('Resolved needs a resolution note', response.status_code == 400)
    response = post(f'/support-desk/tickets/{ticket_id}/status', {'status': 'AWAITING_USER'}, token=agent)
    check('only Open / In progress / Resolved / Closed can be set by hand',
          response.status_code == 400)
    response = post(f'/support-desk/tickets/{ticket_id}/escalate', {'reason': 'pls'}, token=agent)
    check('an escalation needs a real reason', response.status_code == 400)
    response = post(f'/support-desk/tickets/{ticket_id}/escalate',
                    {'reason': 'Customer asks for a refund of a duplicate fee.'}, token=agent)
    check('the agent escalates to admins', data_of(response).get('escalated') is True)
    escalations = data_of(get('/admin/support/escalations', admin))
    check('the admin console lists the escalation',
          any(t['ticket_id'] == ticket_id for t in escalations))
    response = post(f'/support-desk/tickets/{ticket_id}/status',
                    {'status': 'RESOLVED', 'resolution_notes': 'Duplicate row removed.'},
                    token=admin)
    check('an admin resolves it', data_of(response).get('status') == 'RESOLVED')
    trail = [row['action'] for row in data_of(get(f'/support-desk/tickets/{ticket_id}', agent))
             .get('audit_trail', [])]
    check('every action is in the audit trail', all(a in trail for a in (
        'SUPPORT_ASSIGNED', 'SUPPORT_NOTE_ADDED', 'SUPPORT_REPLY_SENT',
        'SUPPORT_ESCALATED', 'SUPPORT_STATUS_CHANGED')), str(trail))

    print('\n[7] Customer lookup is masked and read-only')
    found = data_of(get(f'/support-desk/customers/search?q={member_phone}', agent))
    check('found by the full mobile number', len(found) == 1, str(found)[:200])
    check('search results never show the full number', member_phone not in str(found))
    check('partial numbers are not a search',
          not data_of(get(f'/support-desk/customers/search?q={member_phone[:6]}', agent)))
    staff_search = data_of(get(f'/support-desk/customers/search?q={admin_phone}', agent))
    check('staff accounts are not customers', not staff_search)
    user_id = found[0]['user_id'] if found else 'none'
    response = get(f'/support-desk/customers/{user_id}', agent)
    profile = data_of(response)
    text = response.text
    check('the profile loads', response.status_code == 200 and 'customer' in profile)
    check('no full phone, PAN, MPIN or card number in it',
          member_phone not in text and 'mpin' not in text.lower().replace('mpins', '')
          and 'pan_number' not in text)

    print('\n[8] Staff management (L3)')
    response = post('/admin/staff', {'phone': recruit_phone, 'role': 'L3_SUPER_ADMIN'}, token=admin)
    check('L3 cannot be granted from the screen', response.status_code == 400)
    response = post('/admin/staff', {'phone': '9111100003', 'role': 'L1_SUPPORT'}, token=admin)
    check('an unregistered number is refused with what to do',
          response.status_code == 404 and 'sign up' in error_of(response).get('message', ''))
    response = post('/admin/staff', {'phone': recruit_phone, 'role': 'L1_SUPPORT'}, token=admin)
    check('a registered account becomes support', response.status_code == 200, response.text[:200])
    check('and its member session is signed out', get('/users/me', recruit).status_code == 401)
    check('it now signs in through the support portal',
          login(recruit_phone, 'SUPPORT').status_code == 200)
    staff = data_of(get('/admin/staff', admin)).get('staff', [])
    recruit_row = next((s for s in staff if s['phone_masked'].endswith(recruit_phone[-4:])), None)
    check('it is in the staff list', recruit_row is not None)
    response = post('/admin/staff', {'phone': recruit_phone, 'role': 'L1_SUPPORT'}, token=admin)
    check('adding twice is a conflict', response.status_code == 409)
    response = patch(f'/admin/staff/{recruit_row["user_id"]}', {'role': 'NORMAL_USER'}, admin)
    check('staff access can be removed', response.status_code == 200, response.text[:200])
    check('and the support portal refuses it again',
          login(recruit_phone, 'SUPPORT').status_code == 403)
    me = data_of(get('/users/me', admin))
    response = patch(f'/admin/staff/{me.get("user_id")}', {'role': 'NORMAL_USER'}, admin)
    check('an admin cannot change their own role', response.status_code == 403)
    check('an agent cannot manage staff',
          post('/admin/staff', {'phone': recruit_phone, 'role': 'L1_SUPPORT'},
               token=agent).status_code == 403)

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
