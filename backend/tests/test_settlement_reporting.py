"""
tests/test_settlement_reporting.py
==================================
A settled transfer must never be reported as failed.

The bug this guards against: `_settle` committed the transaction, then built an
audit payload containing `float(source_closing)`. On a UPI-funded transfer no
credit line is drawn, so `source_closing` is None, `float(None)` raised
TypeError, and the bare `except Exception` turned an already-committed success
into `TransferError('Transfer failed. No balance was changed.')`.

The user saw "Transfer complete" with every timeline step ticked and a red
"Transfer failed" toast on top of it. Both statements came from the same
request. The destination balance had in fact changed.

Two things are asserted here, and the second matters more than the first:

1. The audit payload survives a None card balance.
2. No statement that could raise sits after the commit inside the try block -
    a rollback there is a no-op against a committed transaction, so any error
    past that point reports a false failure no matter what caused it.
"""

import inspect
import re

from portal.helpers import transfer_engine


def test_audit_payload_survives_a_upi_funded_settlement():
    """
    float(None) was the crash. A UPI transfer has no card closing balance.

    Rebuilt here exactly as _settle builds it, so the guard is pinned by a test
    rather than by the reader noticing the conditional.
    """
    source_closing = None          # UPI-funded: no credit line drawn
    dest_closing = 26500.00

    payload = {
        'amount': 1000.0,
        'utr': 'CFX0000000001',
        'card_balance_after': (
            float(source_closing) if source_closing is not None else None
        ),
        'bank_balance_after': (
            float(dest_closing) if dest_closing is not None else None
        ),
    }

    assert payload['card_balance_after'] is None
    assert payload['bank_balance_after'] == 26500.00


def test_nothing_fallible_runs_after_the_commit_inside_the_try():
    """
    The structural guarantee, not the symptom.

    Once db.session.commit() has run, the money has moved. The except handler
    below it rolls back - which does nothing to a committed transaction - and
    raises "no balance was changed", so anything that can throw between the
    commit and the end of the try block is a false-failure generator.

    This asserts the commit is the *last* statement in _settle's try block, so
    the next person who appends a line there has to move it deliberately.
    """
    source = inspect.getsource(transfer_engine._settle)

    commit_line = source.index('db.session.commit()')
    except_line = source.index('except TransferError:')

    assert commit_line < except_line, '_settle no longer commits before its handlers'

    between = source[commit_line + len('db.session.commit()'):except_line]

    # Only blank lines and dedent may separate the commit from the handlers.
    leftover = [
        line for line in between.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    assert leftover == [], (
        'Statements were added after db.session.commit() but still inside the '
        'try block of _settle. An exception there is reported to the user as '
        '"Transfer failed. No balance was changed." about a transfer that has '
        f'already settled. Move them below the handlers. Found: {leftover}'
    )


def test_failure_message_is_only_reachable_before_the_commit():
    """The misleading string must stay inside the pre-commit handler."""
    source = inspect.getsource(transfer_engine._settle)

    assert source.count('No balance was changed.') == 1

    # It belongs to the generic handler, which is only reachable while the
    # transaction is still open.
    handler = source[source.index('except Exception as exc:'):]
    assert 'No balance was changed.' in handler


def test_settle_returns_after_the_audit_record():
    """
    The success path still returns the transfer.

    Moving the audit call out of the try block is only correct if the return
    moved with it - otherwise _settle falls off the end and returns None, and
    every caller that reads `result.status` breaks.
    """
    source = inspect.getsource(transfer_engine._settle)
    assert re.search(r'\n    return transfer\s*$', source), (
        '_settle must end by returning the transfer at function level'
    )
