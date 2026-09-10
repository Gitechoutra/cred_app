"""Seed the four RBAC tiers (PRD section 15)."""

import logging

from portal import db
from portal.models.roles import RoleTypes, Roles

logger = logging.getLogger('cashu')

ROLES = [
    (RoleTypes.NORMAL_USER, 'End user - manages their own cards, EMIs and transfers.'),
    (RoleTypes.L1_SUPPORT, 'L1 Support - reads masked profiles and logs.'),
    (RoleTypes.L2_RISK_RECON,
     'L2 Risk and Reconciliation - raw PII (audited), reversals, recon overrides.'),
    (RoleTypes.L3_SUPER_ADMIN,
     'L3 Super Admin - full console including settings and partner keys.'),
]


def seed_roles():
    created = 0

    for role_name, description in ROLES:
        if not Roles.query.filter_by(role_name=role_name).first():
            db.session.add(Roles(
                role_name=role_name, description=description, is_active=True
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_roles: created {created} role(s).')
