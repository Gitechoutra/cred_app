from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class CardStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"       # soft-delete after upstream token revocation
    SUSPENDED = "SUSPENDED"
    TOKEN_FAILED = "TOKEN_FAILED"

    CHOICES = [ACTIVE, EXPIRED, DELETED, SUSPENDED, TOKEN_FAILED]


class Cards(db.Model, TimestampMixin, CRUDMixin):
    """
    A tokenized credit card (PRD FR-003, section 8.2).

    ZERO RAW CARD STORAGE. This table must never gain a column holding a
    16-digit PAN, a CVV, or a card PIN. The card credentials travel from the
    client SDK directly to the licensed Token Requestor; the backend only ever
    sees the network token reference and display metadata.

    Storage status per PRD 8.2:
      PROHIBITED  full PAN, CVV/CVC, card PIN
      PERMITTED   network token, masked PAN, cardholder name, expiry, issuer
    """

    __tablename__ = 'cards'
    __table_args__ = (
        db.Index('ix_cards_user_status', 'user_id', 'status'),
    )

    card_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    # -- Token vault reference (PERMITTED storage) -------------------------
    token_reference_id = db.Column(db.String(255), nullable=False, unique=True)
    token_provider = db.Column(db.String(50), nullable=True)   # e.g. CASHFREE

    masked_pan = db.Column(db.String(25), nullable=False)      # **** **** **** 1234
    last4 = db.Column(db.String(4), nullable=False)
    card_network = db.Column(db.String(20), nullable=False)
    card_issuer_bank = db.Column(db.String(150), nullable=False)
    cardholder_name_enc = db.Column(db.String(512), nullable=True)  # AES-256-GCM

    expiry_month = db.Column(db.String(2), nullable=False)
    expiry_year = db.Column(db.String(4), nullable=False)

    # -- User-maintained limit tracking (FR-004) --------------------------
    # The PRD defers automated statement sync to Phase 2 (Account Aggregator),
    # so in v1 the user configures these and CashU derives utilization.
    card_limit = db.Column(db.Numeric(12, 2), nullable=True)
    available_limit = db.Column(db.Numeric(12, 2), nullable=True)
    outstanding_amount = db.Column(db.Numeric(12, 2), default=0)

    statement_day = db.Column(db.Integer, nullable=True)   # day of month, 1-31
    due_day = db.Column(db.Integer, nullable=True)         # day of month, 1-31
    current_due_amount = db.Column(db.Numeric(12, 2), nullable=True)
    minimum_due_amount = db.Column(db.Numeric(12, 2), nullable=True)
    next_due_date = db.Column(db.Date, nullable=True, index=True)

    brand_color = db.Column(db.String(9), nullable=True)
    nickname = db.Column(db.String(100), nullable=True)

    # Set only for a predefined test card, and only while test mode is on. It
    # is what makes a simulated outcome reproducible: the scenario is chosen
    # when the card is linked, then replayed on every payment it funds.
    # NULL on every real card, which is also how the UI knows what to badge.
    test_scenario = db.Column(db.String(30), nullable=True)

    status = db.Column(db.String(20), default=CardStatus.ACTIVE, nullable=False)

    linked_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    token_revoked_at = db.Column(db.DateTime, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', back_populates='cards')

    def __repr__(self):
        return f"<Card {self.masked_pan} {self.card_issuer_bank}>"

    @property
    def utilization_percentage(self):
        """Percent of the limit currently drawn, or None when no limit is set."""
        if not self.card_limit or float(self.card_limit) == 0:
            return None
        return round(float(self.outstanding_amount or 0) / float(self.card_limit) * 100, 2)
