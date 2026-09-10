"""
Seed the BIN routing table (PRD FR-003).

Only issuer identification numbers are held here - the first six digits, which
identify a bank and are permitted under PCI DSS. There is no card number
anywhere in this file or the table it fills.

brand_color drives the card tile in the UI, so a linked HDFC card looks like an
HDFC card rather than a generic rectangle.
"""

import logging

from portal import db
from portal.models.card_networks import CardNetworks, NetworkType

logger = logging.getLogger('cashu')

V, M, R, A = NetworkType.VISA, NetworkType.MASTERCARD, NetworkType.RUPAY, NetworkType.AMEX

# (bin, network, issuer, type, brand colour, supported)
NETWORKS = [
    # -- HDFC Bank ---------------------------------------------------------
    ('455614', V, 'HDFC Bank', 'CREDIT', '#004C8F', True),
    ('436308', V, 'HDFC Bank', 'CREDIT', '#004C8F', True),
    ('523953', M, 'HDFC Bank', 'CREDIT', '#004C8F', True),
    ('552584', M, 'HDFC Bank', 'CREDIT', '#004C8F', True),
    ('607469', R, 'HDFC Bank', 'CREDIT', '#004C8F', True),

    # -- ICICI Bank --------------------------------------------------------
    ('462938', V, 'ICICI Bank', 'CREDIT', '#AE275F', True),
    ('431307', V, 'ICICI Bank', 'CREDIT', '#AE275F', True),
    ('520139', M, 'ICICI Bank', 'CREDIT', '#AE275F', True),
    ('548809', M, 'ICICI Bank', 'CREDIT', '#AE275F', True),
    ('607385', R, 'ICICI Bank', 'CREDIT', '#AE275F', True),

    # -- State Bank of India ----------------------------------------------
    ('421822', V, 'State Bank of India', 'CREDIT', '#22409A', True),
    ('452147', V, 'State Bank of India', 'CREDIT', '#22409A', True),
    ('533176', M, 'State Bank of India', 'CREDIT', '#22409A', True),
    ('622018', R, 'State Bank of India', 'CREDIT', '#22409A', True),
    ('607094', R, 'State Bank of India', 'CREDIT', '#22409A', True),

    # -- Axis Bank ---------------------------------------------------------
    ('414767', V, 'Axis Bank', 'CREDIT', '#97144D', True),
    ('524315', M, 'Axis Bank', 'CREDIT', '#97144D', True),
    ('556763', M, 'Axis Bank', 'CREDIT', '#97144D', True),
    ('607152', R, 'Axis Bank', 'CREDIT', '#97144D', True),

    # -- Kotak Mahindra ----------------------------------------------------
    ('434582', V, 'Kotak Mahindra Bank', 'CREDIT', '#ED1C24', True),
    ('528358', M, 'Kotak Mahindra Bank', 'CREDIT', '#ED1C24', True),

    # -- Others -------------------------------------------------------------
    ('461797', V, 'IndusInd Bank', 'CREDIT', '#8B1C3F', True),
    ('529110', M, 'IndusInd Bank', 'CREDIT', '#8B1C3F', True),
    ('418228', V, 'IDFC FIRST Bank', 'CREDIT', '#9C1D26', True),
    ('540225', M, 'IDFC FIRST Bank', 'CREDIT', '#9C1D26', True),
    ('465558', V, 'Yes Bank', 'CREDIT', '#00518F', True),
    ('512345', M, 'Standard Chartered', 'CREDIT', '#0473EA', True),
    ('377860', A, 'American Express', 'CREDIT', '#006FCF', True),
    ('376812', A, 'American Express', 'CREDIT', '#006FCF', True),
    ('508227', R, 'Bank of Baroda', 'CREDIT', '#F15A22', True),
    ('607600', R, 'Punjab National Bank', 'CREDIT', '#4B286D', True),
    ('433327', V, 'RBL Bank', 'CREDIT', '#D31245', True),
    ('530598', M, 'AU Small Finance Bank', 'CREDIT', '#5C2D91', True),

    # -- Explicitly unsupported -------------------------------------------
    # PRD ERR-001: only credit cards are supported. These are seeded as
    # unsupported so a debit or prepaid card is refused with the right message
    # rather than an unhelpful "issuer not identified".
    ('411111', V, 'Test Debit Issuer', 'DEBIT', '#6B7674', False),
    ('222100', M, 'Prepaid Gift Card Issuer', 'PREPAID', '#6B7674', False),
]


def seed_card_networks():
    created = 0

    for bin_prefix, network, issuer, card_type, colour, supported in NETWORKS:
        if not CardNetworks.query.filter_by(bin_prefix=bin_prefix).first():
            db.session.add(CardNetworks(
                bin_prefix=bin_prefix,
                network=network,
                issuer_bank=issuer,
                card_type=card_type,
                brand_color=colour,
                is_supported=supported,
                is_blocklisted=False,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_card_networks: created {created} BIN row(s).')
