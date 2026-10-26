"""
CUSTOMER SUPPORT ACCOUNTS - edit this file to manage the support agents' sign-in.

Agents sign in at /support-desk/login with their MOBILE NUMBER + 6-DIGIT MPIN,
and work only from the support desk: L1_SUPPORT sees masked customer data and
cannot move money, change limits or approve anything (see RoleTypes).

How changes apply
-----------------
Save this file (or backend/.env). The backend re-runs the seeders on start, and
the dev server (`python app.py`) restarts by itself when .env is saved:
  * change `phone` / `email` / `mpin` / `full_name` -> that account is updated
    (and signed out everywhere if its phone, email or MPIN changed)
  * add an entry                                    -> a new agent is created
  * remove an entry                                 -> that agent is suspended
Keep each `key` the same for the life of the account - it is how the account
is found when its phone or email changes.

MPINs: exactly 6 digits, not one digit repeated or a run (111111, 123456 are
refused). They are read from backend/.env so they never reach git, and stored
only as a salted hash. An entry whose phone and MPIN are both unset is skipped,
so a fresh checkout boots without any agent.
"""

from portal.models.roles import RoleTypes
from portal.seeders.staff_sync import env, sync_staff

SUPPORT_AGENTS = [
    {
        'key': 'support_agent_1',
        'phone': env('SUPPORT_SEED_PHONE'),
        'email': env('SUPPORT_SEED_EMAIL'),
        'full_name': env('SUPPORT_SEED_NAME') or 'CashU Support',
        'mpin': env('SUPPORT_SEED_MPIN'),
    },
    # Add more agents like this (each with its own .env variables):
    # {
    #     'key': 'support_agent_2',
    #     'phone': env('SUPPORT_2_SEED_PHONE'),
    #     'email': env('SUPPORT_2_SEED_EMAIL'),
    #     'full_name': 'Second Agent',
    #     'mpin': env('SUPPORT_2_SEED_MPIN'),
    # },
]


def seed_customer():
    return sync_staff(SUPPORT_AGENTS, RoleTypes.L1_SUPPORT, 'seed_customer.py')


if __name__ == '__main__':
    # Sync the support agents from this file and backend/.env without starting
    # the server:
    #     cd backend && python -m portal.seeders.seed_customer
    from portal import InitApp

    with InitApp().app().app_context():
        from portal.seeders.seed_roles import seed_roles
        seed_roles()
        print(f'Support agents synced: {seed_customer()}')
