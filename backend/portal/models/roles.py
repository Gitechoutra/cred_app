from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class RoleTypes:
    """PRD section 15 - Role-Based Access Control tiers."""

    NORMAL_USER = "NORMAL_USER"
    L1_SUPPORT = "L1_SUPPORT"
    L2_RISK_RECON = "L2_RISK_RECON"
    L3_SUPER_ADMIN = "L3_SUPER_ADMIN"

    CHOICES = [NORMAL_USER, L1_SUPPORT, L2_RISK_RECON, L3_SUPER_ADMIN]
    ADMIN_ROLES = [L1_SUPPORT, L2_RISK_RECON, L3_SUPER_ADMIN]


class Roles(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'roles'

    role_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    users = db.relationship('Users', back_populates='role', lazy='dynamic')

    def __repr__(self):
        return f"<Role {self.role_name}>"
