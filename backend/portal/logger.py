"""
portal/logger.py
================
Rotating file + stream logging for the CashU backend.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs'
)

_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'


def init_logger(name: str = 'cashu') -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fh = RotatingFileHandler(
            os.path.join(LOG_DIR, 'app.log'),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8',
        )
        fh.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(ch)

    return logger


def audit_logger() -> logging.Logger:
    """
    Separate sink for financial and administrative audit events.

    Kept apart from the application log so it can be shipped to WORM storage
    (PRD 17.1) without dragging debug noise along with it.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger('cashu.audit')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = RotatingFileHandler(
            os.path.join(LOG_DIR, 'audit.log'),
            maxBytes=20 * 1024 * 1024,
            backupCount=20,
            encoding='utf-8',
        )
        fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(fh)

    return logger
