"""
ADMIN ACCOUNTS - edit this file to manage the administrators' sign-in.

A platform with no administrator cannot approve the first KYC, which means no
user can transact - so at least one L3 account is seeded here.

Administrators sign in at /admin/login with their MOBILE NUMBER + 6-DIGIT MPIN.

How changes apply
-----------------
Save this file (or backend/.env). The backend re-runs the seeders on start, and
the dev server (`python app.py`) restarts by itself when .env is saved:
  * change `phone` / `email` / `mpin` / `full_name` -> that account is updated
    (and signed out everywhere if its phone, email or MPIN changed)
  * add an entry                                    -> a new administrator
  * remove an entry                                 -> that account is suspended
Keep each `key` the same for the life of the account - it is how the account
is found when its phone or email changes.

MPINs: exactly 6 digits, not one digit repeated or a run (111111, 123456 are
refused). They are read from backend/.env so they never reach git, and stored
only as a salted hash. There are no built-in defaults: a known default
credential on an account that can change limits and read raw PII is worse than
an administrator who is not created until the variables are set.

Never edit users.mpin_hash by hand - it holds a salted PBKDF2 hash, not the
MPIN; the next boot replaces whatever is there with the .env MPIN anyway.
"""

from portal.models.roles import RoleTypes
from portal.seeders.staff_sync import env, sync_staff

ADMIN_ACCOUNTS = [
    {
        'key': 'admin_1',
        'phone': env('ADMIN_SEED_PHONE'),
        'email': env('ADMIN_SEED_EMAIL'),
        'full_name': env('ADMIN_SEED_NAME') or 'CashU Administrator',
        'mpin': env('ADMIN_SEED_MPIN'),
    },
    # Add more administrators like this (each with its own .env variables):
    # {
    #     'key': 'admin_2',
    #     'phone': env('ADMIN_2_SEED_PHONE'),
    #     'email': env('ADMIN_2_SEED_EMAIL'),
    #     'full_name': 'Second Administrator',
    #     'mpin': env('ADMIN_2_SEED_MPIN'),
    # },
]


def seed_admin():
    return sync_staff(ADMIN_ACCOUNTS, RoleTypes.L3_SUPER_ADMIN, 'seed_admin.py')


if __name__ == '__main__':
    # Sync the administrators from this file and backend/.env without starting
    # the server:
    #     cd backend && python -m portal.seeders.seed_admin
    from portal import InitApp

    with InitApp().app().app_context():
        from portal.seeders.seed_roles import seed_roles
        seed_roles()
        print(f'Administrators synced: {seed_admin()}')
