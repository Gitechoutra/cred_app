from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class CardTheme:
    """
    How a card is drawn. Purely visual: a theme never changes a figure, a
    status or what a card is allowed to do.

    AUTO takes the colours of the issuing bank's logo (the frontend's
    BANK_CARD_THEMES). The rest are fixed palettes a holder may pick instead.
    """

    AUTO = 'AUTO'
    MATTE_BLACK = 'MATTE_BLACK'      # matte black, silver accents
    DEEP_BLUE = 'DEEP_BLUE'          # deep blue and white
    SUNSET = 'SUNSET'                # orange into deep blue
    NAVY_SKY = 'NAVY_SKY'            # navy into light blue
    BURGUNDY = 'BURGUNDY'            # burgundy into dark red
    BLUE_SILVER = 'BLUE_SILVER'      # blue and silver
    PURPLE = 'PURPLE'
    TEAL = 'TEAL'
    AURORA = 'AURORA'                # a premium multi-colour gradient

    CHOICES = [AUTO, MATTE_BLACK, DEEP_BLUE, SUNSET, NAVY_SKY, BURGUNDY,
               BLUE_SILVER, PURPLE, TEAL, AURORA]


class ManualCardStatus:
    ACTIVE = 'ACTIVE'
    REMOVED = 'REMOVED'

    CHOICES = [ACTIVE, REMOVED]


class ManualCardNetwork:
    VISA = 'VISA'
    MASTERCARD = 'MASTERCARD'
    RUPAY = 'RUPAY'
    AMEX = 'AMEX'
    DINERS = 'DINERS'
    OTHER = 'OTHER'

    CHOICES = [VISA, MASTERCARD, RUPAY, AMEX, DINERS, OTHER]


class ManualCards(db.Model, TimestampMixin, CRUDMixin):
    """
    A credit card the holder tracks by typing its figures in.

    Kept apart from `cards` on purpose. A row in `cards` is tokenised and its
    limit is set by CashU; the payment and limit code reads that table. Every
    figure here was typed by the holder and is labelled "User-entered - Not
    Bank Verified" wherever it is shown, so it lives where no money path can
    mistake it for a limit CashU granted.

    Holds no card number beyond the last four digits, no CVV, no expiry, no
    PIN and no bank credentials - the form never asks for them.
    """

    __tablename__ = 'manual_cards'
    __table_args__ = (
        db.Index('ix_manual_cards_user_status', 'user_id', 'status'),
        db.Index('ix_manual_cards_user_issuer_last4', 'user_id', 'issuer_bank', 'last4'),
    )

    manual_card_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    issuer_bank = db.Column(db.String(150), nullable=False)
    #: The bank's id in the frontend's supported-bank list, when it is one.
    issuer_id = db.Column(db.String(40), nullable=True)
    nickname = db.Column(db.String(100), nullable=True)
    network = db.Column(db.String(20), nullable=False, default=ManualCardNetwork.OTHER)
    last4 = db.Column(db.String(4), nullable=False)

    # -- Holder-entered figures, all optional ------------------------------
    credit_limit = db.Column(db.Numeric(14, 2), nullable=True)
    outstanding_balance = db.Column(db.Numeric(14, 2), nullable=True)
    #: As the holder gave it. When they gave only a limit and a balance, the
    #: API shows limit minus balance and says it was worked out.
    available_credit = db.Column(db.Numeric(14, 2), nullable=True)
    statement_day = db.Column(db.Integer, nullable=True)       # 1-31
    payment_due_date = db.Column(db.Date, nullable=True)
    minimum_due = db.Column(db.Numeric(14, 2), nullable=True)
    total_due = db.Column(db.Numeric(14, 2), nullable=True)

    theme = db.Column(db.String(20), nullable=False, default=CardTheme.AUTO)
    status = db.Column(db.String(10), nullable=False, default=ManualCardStatus.ACTIVE)
    removed_at = db.Column(db.DateTime, nullable=True)
    #: When the holder last changed any figure - the "last updated" shown.
    figures_updated_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<ManualCard {self.issuer_bank} {self.last4} {self.status}>'
