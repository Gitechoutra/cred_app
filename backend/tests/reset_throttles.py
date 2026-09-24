"""
Clear the rate-limit counters. Development only.

The live suites each register a user, and OTP sending is limited per phone and
per source address. Every suite uses a fresh random phone, so the per-phone
bucket is never the problem - but the per-IP bucket is shared, and it allows
OTP_MAX_RESENDS_PER_WINDOW * 3 sends per window from one host. Running the full
set back to back fits inside that; running one suite repeatedly while debugging
does not, and the window is 15 minutes.

So this exists to reset the counters between runs, rather than have the suites
sleep out a quarter-hour or, worse, treat the limiter as something to weaken.

    python tests/reset_throttles.py

Refuses outside a development environment: these counters are a security
control, and clearing them anywhere real is an attack, not a convenience.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portal import InitApp, db                              # noqa: E402
from portal.models.rate_limit_counters import RateLimitCounters   # noqa: E402


def main():
    environment = (os.getenv('Backend', 'DEV') or 'DEV').upper()
    if environment != 'DEV':
        print(f'Refusing to clear rate limits in {environment}.')
        return 1

    app = InitApp().app()
    with app.app_context():
        removed = RateLimitCounters.query.delete()
        db.session.commit()

    print(f'Cleared {removed} rate-limit counter row(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
