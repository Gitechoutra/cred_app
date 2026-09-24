"""
Shared throttle handling for the live suites.

Every suite in here drives a real backend from one address, in a burst, and the
platform throttles exactly that (ERR-011). A 429 is therefore the rate limiter
working correctly - but a suite that records it as a result reports something
untrue: the first check reads "OTP issued: FAIL" and the forty after it read
403, none of which says anything about the code under test.

So a 429 is waited out, using the server's own retry_after_seconds, and the
suite continues. This never hides a real outcome, because no check in any of
these suites asserts a 429; the rate limiter itself is covered by
validation_audit's own section, which asserts the limit is *reached* rather than
asserting a particular response to one request.

Bounded at three waits so a genuinely wedged limiter fails the run rather than
hanging it.
"""

import time

MAX_WAITS = 3
DEFAULT_WAIT_SECONDS = 5
MAX_WAIT_SECONDS = 30


def _retry_after(response):
    try:
        body = response.json()
    except ValueError:
        return DEFAULT_WAIT_SECONDS
    details = (body.get('error') or {}).get('details') or {}
    return details.get('retry_after_seconds') or DEFAULT_WAIT_SECONDS


def throttled(send):
    """
    Run `send()`, waiting out a 429 rather than returning it.

    `send` is a zero-argument callable so the request can be re-issued exactly
    as it was, headers and body included.
    """
    for _ in range(MAX_WAITS):
        response = send()
        if response.status_code != 429:
            return response
        time.sleep(min(float(_retry_after(response)) + 1, MAX_WAIT_SECONDS))
    return send()
