"""
portal/helpers/encryption.py
============================
AES-256-GCM field-level encryption for PII at rest (PRD 17.1).

Covers PAN, Aadhaar, bank account numbers, loan account numbers and cardholder
names. GCM is authenticated encryption: a tampered ciphertext fails to decrypt
rather than returning plausible garbage, which matters when the plaintext is
routed straight into a payout instruction.

Stored format is a single base64 string: nonce (12 bytes) || ciphertext || tag.
Everything needed to decrypt travels with the value, so no column needs to hold
a nonce separately.
"""

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app

_NONCE_BYTES = 12   # GCM standard; 96-bit nonce is what the mode is built for
_KEY_BYTES = 32     # AES-256


class EncryptionError(Exception):
    pass


def _key() -> bytes:
    """
    Resolve the 32-byte master key.

    In production this comes from AWS KMS or HashiCorp Vault (PRD 17.1). Here it
    is a base64 env var. A missing key is fatal rather than silently defaulted:
    a predictable key would make every encrypted column readable by anyone with
    the source, which is worse than refusing to boot.
    """
    raw = current_app.config.get('FIELD_ENCRYPTION_KEY') or os.getenv(
        'FIELD_ENCRYPTION_KEY', ''
    )
    if not raw:
        raise EncryptionError(
            'FIELD_ENCRYPTION_KEY is not set. Generate one with: '
            'python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"'
        )

    try:
        key = base64.b64decode(raw)
    except Exception as exc:
        raise EncryptionError(f'FIELD_ENCRYPTION_KEY is not valid base64: {exc}')

    if len(key) != _KEY_BYTES:
        raise EncryptionError(
            f'FIELD_ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes, got {len(key)}'
        )
    return key


def encrypt(plaintext: str) -> str:
    """Encrypt a string for storage. Returns base64(nonce || ciphertext || tag)."""
    if plaintext is None or plaintext == '':
        return ''

    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt(stored: str) -> str:
    """Reverse of encrypt(). Raises EncryptionError on tampering or a bad key."""
    if not stored:
        return ''

    try:
        blob = base64.b64decode(stored)
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(_key()).decrypt(nonce, ciphertext, None).decode('utf-8')
    except EncryptionError:
        raise
    except Exception as exc:
        # Deliberately vague: the caller does not need to know whether the key
        # was wrong or the ciphertext was edited, and neither should a log.
        raise EncryptionError(f'Failed to decrypt stored value: {type(exc).__name__}')


def blind_index(value: str) -> str:
    """
    Deterministic SHA-256 hash for equality lookups on encrypted columns.

    AES-GCM is randomised, so two encryptions of the same account number differ
    and a WHERE clause cannot find duplicates. This gives a stable, searchable
    fingerprint. It is keyed with the master key so the hash cannot be brute
    forced offline from the (small) space of Indian account numbers.
    """
    if not value:
        return ''
    return hmac.new(_key(), value.encode('utf-8'), hashlib.sha256).hexdigest()


# ── One-way hashing for secrets that are verified, never read back ──────────

def hash_secret(secret: str) -> str:
    """
    Salted PBKDF2 for OTPs, MPINs and refresh tokens.

    A 6-digit MPIN has only a million possibilities, so plain SHA-256 would fall
    to a rainbow table instantly. 120k PBKDF2 iterations make an offline sweep
    of the whole space cost real time.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', secret.encode('utf-8'), salt, 120_000)
    return f"pbkdf2_sha256$120000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_secret(secret: str, stored: str) -> bool:
    """Constant-time verification against hash_secret() output."""
    if not stored or not secret:
        return False
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        dk = hashlib.pbkdf2_hmac(
            'sha256',
            secret.encode('utf-8'),
            base64.b64decode(salt_b64),
            int(iterations),
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


def mask_pan(last4: str) -> str:
    """Render a card as the PRD 8.2 permitted display form."""
    return f"**** **** **** {last4}" if last4 else "**** **** **** ****"


def mask_account(last4: str) -> str:
    return f"**** {last4}" if last4 else "****"


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "******"
    return f"{'*' * (len(phone) - 4)}{phone[-4:]}"
