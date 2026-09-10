"""
portal/helpers/name_match.py
============================
Penny-drop name matching (PRD FR-005).

Compares the account holder name returned by the bank's core banking system
against the user's KYC legal name, and produces a confidence score that decides
whether a payout destination is accepted.

    >= 80    VERIFIED             account accepted instantly
    70 - 80  NAME_MISMATCH        held for compliance review
    < 70     MANUAL_REVIEW_KYC    PMLA hold, third-party account suspected

The thresholds are settings, not constants, because the right cut-off is a risk
appetite decision an operator may need to tighten without a deploy.

Why this needs more than a string compare: Indian bank records are inconsistent
in ways that are not the user's fault. "RAJESH KUMAR SHARMA" at the bank may be
"Rajesh K Sharma" on the PAN. Honorifics, initials, word order and spacing all
vary. Scoring several strategies and taking the best avoids rejecting a
legitimate account over a middle initial, while still catching a genuinely
different person.
"""

import re

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from portal.helpers import settings
from portal.helpers.settings import Key

#: Stripped before comparison - they carry no identity information.
_HONORIFICS = {
    'mr', 'mrs', 'ms', 'miss', 'dr', 'shri', 'smt', 'sri', 'kum',
    'prof', 'md', 'late', 'm/s',
}

_NOISE_RE = re.compile(r'[^a-z\s]')
_SPACE_RE = re.compile(r'\s+')


def normalize(name: str) -> str:
    """Lowercase, strip punctuation and honorifics, collapse whitespace."""
    if not name:
        return ''

    text = _NOISE_RE.sub(' ', str(name).lower())
    tokens = [t for t in _SPACE_RE.split(text) if t and t not in _HONORIFICS]
    return ' '.join(tokens)


def _initials_expanded(a_tokens, b_tokens) -> float:
    """
    Score a name written with initials against one written in full.

    "rajesh k sharma" vs "rajesh kumar sharma": a single-letter token matches a
    full token that starts with the same letter. Without this, a middle initial
    drags an otherwise perfect match below the threshold.
    """
    if len(a_tokens) != len(b_tokens):
        return 0.0

    matched = 0
    for x, y in zip(a_tokens, b_tokens):
        if x == y:
            matched += 1
        elif len(x) == 1 and y.startswith(x):
            matched += 1
        elif len(y) == 1 and x.startswith(y):
            matched += 1

    return (matched / len(a_tokens)) * 100 if a_tokens else 0.0


def score(cbs_name: str, kyc_name: str) -> float:
    """
    Confidence that two names refer to the same person, 0.00 to 100.00.

    Takes the best of several strategies rather than averaging: each handles a
    different real-world distortion, and a name that matches strongly under any
    one of them is the same person. Averaging would let one inapplicable
    strategy drag a genuine match under the line.
    """
    left, right = normalize(cbs_name), normalize(kyc_name)

    if not left or not right:
        return 0.0
    if left == right:
        return 100.0

    left_tokens = left.split()
    right_tokens = right.split()

    candidates = [
        # Character-level similarity, weighted toward a common prefix.
        JaroWinkler.similarity(left, right) * 100,
        # Levenshtein ratio - catches transpositions and typos.
        fuzz.ratio(left, right),
        # Word order independent: "sharma rajesh" vs "rajesh sharma".
        fuzz.token_sort_ratio(left, right),
        # Subset tolerant: handles an extra or missing middle name.
        fuzz.token_set_ratio(left, right),
        _initials_expanded(left_tokens, right_tokens),
    ]

    return round(max(candidates), 2)


def evaluate(cbs_name: str, kyc_name: str) -> dict:
    """
    Score a pair and map it onto a penny-drop status.

    Returns the decision plus the reason, both of which are persisted on the
    verification row so a compliance officer reviewing a hold later can see
    exactly why it was held.
    """
    from portal.models.bank_accounts import PennyDropStatus

    verified_at = settings.get_decimal(Key.PENNY_DROP_MATCH_THRESHOLD)
    review_at = settings.get_decimal(Key.PENNY_DROP_REVIEW_THRESHOLD)

    confidence = score(cbs_name, kyc_name)

    if confidence >= float(verified_at):
        status = PennyDropStatus.VERIFIED
        reason = f'Name matched at {confidence}% confidence.'
    elif confidence >= float(review_at):
        status = PennyDropStatus.NAME_MISMATCH
        reason = (
            f'Name matched at only {confidence}% confidence; '
            'held for compliance review.'
        )
    else:
        status = PennyDropStatus.MANUAL_REVIEW_KYC
        reason = (
            f'Name match confidence {confidence}% is below the acceptable '
            'threshold. Held under PMLA third-party transfer rules.'
        )

    return {
        'score': confidence,
        'status': status,
        'reason': reason,
        'cbs_name': cbs_name,
        'kyc_name': kyc_name,
        'verified_threshold': float(verified_at),
        'review_threshold': float(review_at),
    }
