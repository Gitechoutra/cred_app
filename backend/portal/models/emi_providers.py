from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class ProviderIntegrationMode:
    BBPS = "BBPS"                # routed via a licensed BBPOU
    DIRECT_API = "DIRECT_API"    # provider B2B API
    MANUAL = "MANUAL"            # user-entered, admin-verified

    CHOICES = [BBPS, DIRECT_API, MANUAL]


class EMIProviders(db.Model, TimestampMixin, CRUDMixin):
    """
    NBFC and bank lenders whose EMIs CashU can service (PRD FR-007, 10.1).

    The PRD requires an abstract EMIProviderAdapter so a new lender can be
    added without touching core code. This table is the registry side of that:
    adapter_key selects the implementation, everything else is configuration.
    """

    __tablename__ = 'emi_providers'

    provider_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    provider_name = db.Column(db.String(150), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(150), nullable=False)
    adapter_key = db.Column(db.String(50), nullable=False)      # e.g. bajaj_finance
    integration_mode = db.Column(db.String(20), default=ProviderIntegrationMode.BBPS)

    bbps_biller_id = db.Column(db.String(50), nullable=True)
    logo_path = db.Column(db.String(500), nullable=True)
    brand_color = db.Column(db.String(9), nullable=True)

    supports_auto_fetch = db.Column(db.Boolean, default=False)
    supports_auto_pay = db.Column(db.Boolean, default=True)
    # Regex the LAN must satisfy before a lookup is attempted (ERR-010).
    loan_account_pattern = db.Column(db.String(200), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=100)

    obligations = db.relationship(
        'EMIObligations', back_populates='provider', lazy='dynamic'
    )

    def __repr__(self):
        return f"<EMIProvider {self.provider_name}>"
