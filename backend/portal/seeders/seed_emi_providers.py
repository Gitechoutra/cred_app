"""
Seed the lender registry (PRD FR-007, section 10.1).

Bajaj Finance is the anchor launch provider named in the PRD. The rest are
Phase 1.1 and are seeded inactive so the directory can be opened up by flipping
a row rather than shipping code.
"""

import logging

from portal import db
from portal.models.emi_providers import EMIProviders, ProviderIntegrationMode

logger = logging.getLogger('cashu')

BBPS = ProviderIntegrationMode.BBPS
DIRECT = ProviderIntegrationMode.DIRECT_API
MANUAL = ProviderIntegrationMode.MANUAL

# (name, display, adapter key, mode, auto-fetch, auto-pay, colour, order, active)
PROVIDERS = [
    ('BAJAJ_FINANCE', 'Bajaj Finserv', 'bajaj_finance', DIRECT,
     True, True, '#0B4DA2', 1, True),
    ('HDB_FINANCIAL', 'HDB Financial Services', 'hdb_financial', BBPS,
     True, True, '#004C8F', 2, True),
    ('IDFC_FIRST', 'IDFC FIRST Bank', 'idfc_first', BBPS,
     True, True, '#9C1D26', 3, True),
    ('HOME_CREDIT', 'Home Credit', 'home_credit', BBPS,
     True, True, '#E4002B', 4, False),
    ('TVS_CREDIT', 'TVS Credit', 'tvs_credit', BBPS,
     True, True, '#00539B', 5, False),
    ('TATA_CAPITAL', 'Tata Capital', 'tata_capital', BBPS,
     True, True, '#486AAE', 6, False),
    ('OTHER', 'Other Lender', 'manual', MANUAL,
     False, False, '#6B7674', 99, True),
]


def seed_emi_providers():
    created = 0

    for (name, display, adapter_key, mode, auto_fetch,
         auto_pay, colour, order, active) in PROVIDERS:
        if not EMIProviders.query.filter_by(provider_name=name).first():
            db.session.add(EMIProviders(
                provider_name=name,
                display_name=display,
                adapter_key=adapter_key,
                integration_mode=mode,
                supports_auto_fetch=auto_fetch,
                supports_auto_pay=auto_pay,
                brand_color=colour,
                display_order=order,
                is_active=active,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_emi_providers: created {created} provider(s).')
