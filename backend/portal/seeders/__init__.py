"""
portal/seeders/__init__.py
==========================
Central seeder registry - runs every seeder in dependency order.

All seeders are idempotent: they insert what is missing and leave what exists
alone, so they are safe on every boot. That matters because app.py runs them at
import time, which means they execute on every restart and every deploy.

Usage in app.py:

    with app.app_context():
        db.create_all()
        from portal.seeders import run_all_seeders
        run_all_seeders()
"""

import logging

logger = logging.getLogger('cashu')


def run_all_seeders():
    """
    Seed in strict dependency order:

        1. roles              ADMIN tiers must exist before any user
        2. ledger_accounts    the chart of accounts must exist before any posting
        3. admin_settings     limits and fees the engines read at runtime
        4. feature_flags      feature toggles, defaulting closed where risky
        5. card_networks      BIN routing table for card linking
        6. emi_providers      lender registry
        7. notification_templates  copy for the PRD 14.1 matrix
        8. admin             the bootstrap administrator account
    """
    logger.info('[Seeders] Starting database seeding...')

    steps = [
        ('seed_roles', 'portal.seeders.seed_roles'),
        ('seed_ledger_accounts', 'portal.seeders.seed_ledger_accounts'),
        ('seed_admin_settings', 'portal.seeders.seed_admin_settings'),
        ('seed_feature_flags', 'portal.seeders.seed_feature_flags'),
        ('seed_card_networks', 'portal.seeders.seed_card_networks'),
        ('seed_emi_providers', 'portal.seeders.seed_emi_providers'),
        ('seed_notification_templates', 'portal.seeders.seed_notification_templates'),
        ('seed_admin', 'portal.seeders.seed_admin'),
    ]

    for function_name, module_path in steps:
        try:
            module = __import__(module_path, fromlist=[function_name])
            getattr(module, function_name)()
        except Exception as exc:
            # Raise rather than continue: a partially seeded database is worse
            # than a failed boot, because the engines would then read a missing
            # ledger account or limit as a silent default.
            logger.error(f'[Seeders] {function_name} FAILED: {exc}')
            raise

    logger.info('[Seeders] All seeders completed successfully.')
