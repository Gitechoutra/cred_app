from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class NetworkType:
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    RUPAY = "RUPAY"
    AMEX = "AMEX"
    DINERS = "DINERS"

    CHOICES = [VISA, MASTERCARD, RUPAY, AMEX, DINERS]


class CardNetworks(db.Model, TimestampMixin, CRUDMixin):
    """
    BIN/IIN routing reference (PRD FR-003: issuer identified via the first six
    digits). Seeded, not user-editable.

    Only the BIN prefix is held here - never a full card number.
    """

    __tablename__ = 'card_networks'

    network_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    bin_prefix = db.Column(db.String(8), nullable=False, index=True)
    network = db.Column(db.String(20), nullable=False)
    issuer_bank = db.Column(db.String(150), nullable=False)
    card_type = db.Column(db.String(20), default='CREDIT')   # CREDIT | DEBIT | PREPAID

    brand_color = db.Column(db.String(9), nullable=True)     # UI theming per issuer
    logo_path = db.Column(db.String(500), nullable=True)

    # ERR-001: the platform supports credit cards only. Prepaid and gift cards
    # are rejected before they ever reach the token requestor.
    is_supported = db.Column(db.Boolean, default=True)
    is_blocklisted = db.Column(db.Boolean, default=False)    # PRD 16.1 risk rules

    def __repr__(self):
        return f"<CardNetwork {self.bin_prefix} {self.issuer_bank}>"
