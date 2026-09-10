"""
portal/models/base.py
=====================
Shared column types and instance helpers for every CashU model.

Financial entities use UUIDv4 primary keys (PRD sections 13.1 and 23) rather than
sequential integers: transfer and transaction identifiers are handed to users in
receipts and URLs, and a sequential id there leaks platform volume and lets one
user enumerate another's records. Reference tables keep integer keys.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CHAR

from portal import db


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC. MySQL DATETIME carries no zone, so everything is stored UTC
    and rendered in IST at the edge."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


#: Primary/foreign key column type for UUID-keyed entities.
UUIDColumn = CHAR(36)


def uuid_pk():
    return db.Column(UUIDColumn, primary_key=True, default=gen_uuid)


def uuid_fk(target: str, **kwargs):
    return db.Column(UUIDColumn, db.ForeignKey(target), **kwargs)


class TimestampMixin:
    created_on = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_on = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CRUDMixin:
    """save/update/delete helpers, matching the house style."""

    def save(self):
        db.session.add(self)
        db.session.commit()
        return self

    def update(self):
        db.session.commit()
        return self

    def delete(self):
        db.session.delete(self)
        db.session.commit()


class AppendOnlyMixin(CRUDMixin):
    """
    For ledger and transaction rows.

    PRD FR-010: "Financial records cannot be hard-deleted or modified under any
    circumstance. All adjustments must be written as compensating journal
    entries." Removing delete() means a stray call is an AttributeError at
    import time rather than a silent hole in the audit trail.
    """

    def delete(self):
        raise NotImplementedError(
            f"{type(self).__name__} is append-only (PRD FR-010). "
            "Post a compensating entry instead of deleting."
        )
