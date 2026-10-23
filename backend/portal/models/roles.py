from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class RoleTypes:
    """PRD section 15 - Role-Based Access Control tiers."""

    NORMAL_USER = "NORMAL_USER"
    L1_SUPPORT = "L1_SUPPORT"
    L2_RISK_RECON = "L2_RISK_RECON"
    L3_SUPER_ADMIN = "L3_SUPER_ADMIN"

    CHOICES = [NORMAL_USER, L1_SUPPORT, L2_RISK_RECON, L3_SUPER_ADMIN]
    #: Who may open the admin console. Support agents are deliberately not
    #: here: they work from the support desk, which shows masked customer data
    #: and cannot move money, change limits or approve anything.
    ADMIN_ROLES = [L2_RISK_RECON, L3_SUPER_ADMIN]
    #: Who may sign in to the support desk portal.
    SUPPORT_ROLES = [L1_SUPPORT]
    #: Who may use the support desk endpoints: agents, and administrators
    #: handling escalations.
    SUPPORT_DESK_ROLES = [L1_SUPPORT, L2_RISK_RECON, L3_SUPER_ADMIN]
    #: Every staff role. A staff account does not use the member app.
    STAFF_ROLES = [L1_SUPPORT, L2_RISK_RECON, L3_SUPER_ADMIN]

    #: Sign-in portals and the roles each one admits.
    PORTALS = {
        'USER': [NORMAL_USER],
        'ADMIN': ADMIN_ROLES,
        'SUPPORT': SUPPORT_ROLES,
    }


class Roles(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'roles'

    role_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    users = db.relationship('Users', back_populates='role', lazy='dynamic')

    def __repr__(self):
        return f"<Role {self.role_name}>"
