"""
portal/helpers/bank_ifsc_service.py
===================================
Centralized Bank & IFSC lookup service.
Validates IFSC format, maps IFSC prefixes to official bank / financial institution
names, branches, and provides test account details.
"""

import re
from decimal import Decimal

IFSC_REGEX = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')

# Authoritative mapping of IFSC prefix (first 4 characters) to Bank / Institution details
IFSC_INSTITUTION_MAP = {
    'SBIN': {
        'bank_name': 'State Bank of India (SBI)',
        'short_name': 'SBI',
        'type': 'PUBLIC_SECTOR_BANK',
        'branch': 'Guntur Main Branch',
        'city': 'Guntur',
        'state': 'Andhra Pradesh',
    },
    'HDFC': {
        'bank_name': 'HDFC Bank',
        'short_name': 'HDFC',
        'type': 'PRIVATE_BANK',
        'branch': 'Banjara Hills Branch',
        'city': 'Hyderabad',
        'state': 'Telangana',
    },
    'ICIC': {
        'bank_name': 'ICICI Bank',
        'short_name': 'ICICI',
        'type': 'PRIVATE_BANK',
        'branch': 'Cyber City Branch',
        'city': 'Gurugram',
        'state': 'Haryana',
    },
    'AXIS': {
        'bank_name': 'Axis Bank',
        'short_name': 'Axis',
        'type': 'PRIVATE_BANK',
        'branch': 'MG Road Branch',
        'city': 'Bengaluru',
        'state': 'Karnataka',
    },
    'KKBK': {
        'bank_name': 'Kotak Mahindra Bank',
        'short_name': 'Kotak',
        'type': 'PRIVATE_BANK',
        'branch': 'BKC Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'PUNB': {
        'bank_name': 'Punjab National Bank (PNB)',
        'short_name': 'PNB',
        'type': 'PUBLIC_SECTOR_BANK',
        'branch': 'Connaught Place Branch',
        'city': 'New Delhi',
        'state': 'Delhi',
    },
    'BARB': {
        'bank_name': 'Bank of Baroda',
        'short_name': 'BOB',
        'type': 'PUBLIC_SECTOR_BANK',
        'branch': 'Alkapuri Branch',
        'city': 'Vadodara',
        'state': 'Gujarat',
    },
    'UBIN': {
        'bank_name': 'Union Bank of India',
        'short_name': 'UBI',
        'type': 'PUBLIC_SECTOR_BANK',
        'branch': 'Fort Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'CNRB': {
        'bank_name': 'Canara Bank',
        'short_name': 'Canara',
        'type': 'PUBLIC_SECTOR_BANK',
        'branch': 'Town Hall Branch',
        'city': 'Bengaluru',
        'state': 'Karnataka',
    },
    'IDFB': {
        'bank_name': 'IDFC FIRST Bank',
        'short_name': 'IDFC FIRST',
        'type': 'PRIVATE_BANK',
        'branch': 'BKC Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'YESB': {
        'bank_name': 'Yes Bank',
        'short_name': 'Yes Bank',
        'type': 'PRIVATE_BANK',
        'branch': 'Worli Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'INDB': {
        'bank_name': 'IndusInd Bank',
        'short_name': 'IndusInd',
        'type': 'PRIVATE_BANK',
        'branch': 'Nariman Point Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'FDRL': {
        'bank_name': 'Federal Bank',
        'short_name': 'Federal',
        'type': 'PRIVATE_BANK',
        'branch': 'Aluva Branch',
        'city': 'Ernakulam',
        'state': 'Kerala',
    },
    'RBLN': {
        'bank_name': 'RBL Bank',
        'short_name': 'RBL',
        'type': 'PRIVATE_BANK',
        'branch': 'Lower Parel Branch',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    # Non-bank and specialized financial institutions
    'BAJA': {
        'bank_name': 'Bajaj Finance',
        'short_name': 'Bajaj Finance',
        'type': 'FINANCIAL_INSTITUTION',
        'branch': 'Akurdi Head Office',
        'city': 'Pune',
        'state': 'Maharashtra',
    },
    'BAJF': {
        'bank_name': 'Bajaj Finance',
        'short_name': 'Bajaj Finance',
        'type': 'FINANCIAL_INSTITUTION',
        'branch': 'Akurdi Head Office',
        'city': 'Pune',
        'state': 'Maharashtra',
    },
    'TATA': {
        'bank_name': 'Tata Capital Financial Services',
        'short_name': 'Tata Capital',
        'type': 'FINANCIAL_INSTITUTION',
        'branch': 'Peninsula Business Park',
        'city': 'Mumbai',
        'state': 'Maharashtra',
    },
    'HDBF': {
        'bank_name': 'HDB Financial Services',
        'short_name': 'HDB',
        'type': 'FINANCIAL_INSTITUTION',
        'branch': 'Radhika Branch',
        'city': 'Ahmedabad',
        'state': 'Gujarat',
    },
    'TVSC': {
        'bank_name': 'TVS Credit Services',
        'short_name': 'TVS Credit',
        'type': 'FINANCIAL_INSTITUTION',
        'branch': 'Jayalakshmi Estates',
        'city': 'Chennai',
        'state': 'Tamil Nadu',
    },
    'PAYT': {
        'bank_name': 'Paytm Payments Bank',
        'short_name': 'Paytm',
        'type': 'PAYMENTS_BANK',
        'branch': 'Noida Sector 5 Branch',
        'city': 'Noida',
        'state': 'Uttar Pradesh',
    },
    'AIRP': {
        'bank_name': 'Airtel Payments Bank',
        'short_name': 'Airtel',
        'type': 'PAYMENTS_BANK',
        'branch': 'Gurugram Central Branch',
        'city': 'Gurugram',
        'state': 'Haryana',
    },
}

# Predefined TEST bank accounts directory for testing
PREDEFINED_TEST_ACCOUNTS = {
    '123456789012': {
        'ifsc_code': 'SBIN0001234',
        'bank_name': 'State Bank of India (SBI)',
        'branch_name': 'Guntur Main Branch',
        'account_holder_name': 'Lingam Revanth',
        'account_type': 'SAVINGS',
        'balance': Decimal('20000.00'),
        'is_active': True,
    },
    '987654321098': {
        'ifsc_code': 'HDFC0001234',
        'bank_name': 'HDFC Bank',
        'branch_name': 'Banjara Hills Branch',
        'account_holder_name': 'Vikram Sharma',
        'account_type': 'SAVINGS',
        'balance': Decimal('25000.00'),
        'is_active': True,
    },
    '112233445566': {
        'ifsc_code': 'ICIC0001234',
        'bank_name': 'ICICI Bank',
        'branch_name': 'Cyber City Branch',
        'account_holder_name': 'Test User',
        'account_type': 'SAVINGS',
        'balance': Decimal('30000.00'),
        'is_active': True,
    },
    '556677889900': {
        'ifsc_code': 'BAJF0001234',
        'bank_name': 'Bajaj Finance',
        'branch_name': 'Akurdi Head Office',
        'account_holder_name': 'Bajaj Finance Settlement Account',
        'account_type': 'CURRENT',
        'balance': Decimal('50000.00'),
        'is_active': True,
    },
}


def validate_ifsc_format(ifsc: str) -> tuple[bool, str]:
    """Check if the IFSC code has valid format."""
    code = (ifsc or '').strip().upper()
    if not code or len(code) != 11:
        return False, 'Invalid IFSC code.'
    if not IFSC_REGEX.match(code):
        return False, 'Invalid IFSC code.'
    return True, code


def get_bank_info(ifsc: str) -> dict:
    """
    Identify bank/institution name and branch details from IFSC.
    Supports conventional banks, payments banks, and financial institutions (NBFCs).
    """
    valid, code = validate_ifsc_format(ifsc)
    if not valid:
        return {
            'ok': False,
            'error': 'Invalid IFSC code.',
        }

    prefix = code[:4]
    info = IFSC_INSTITUTION_MAP.get(prefix)
    if not info:
        return {
            'ok': False,
            'error': f'Unsupported bank/institution code: {prefix}. Please check the IFSC code.',
        }

    return {
        'ok': True,
        'ifsc': code,
        'bank_name': info['bank_name'],
        'short_name': info['short_name'],
        'institution_type': info['type'],
        'branch': info.get('branch', 'Main Branch'),
        'city': info.get('city', 'Mumbai'),
        'state': info.get('state', 'Maharashtra'),
    }


def lookup_test_account(account_no: str, ifsc: str = None) -> dict | None:
    """
    Retrieve test account details from predefined dataset or existing database.
    """
    clean_acc = (account_no or '').strip().replace(' ', '')
    clean_ifsc = (ifsc or '').strip().upper() if ifsc else None

    # 1. Check predefined test accounts
    if clean_acc in PREDEFINED_TEST_ACCOUNTS:
        acc_data = PREDEFINED_TEST_ACCOUNTS[clean_acc]
        if clean_ifsc and acc_data['ifsc_code'] != clean_ifsc:
            return None
        return {
            'account_number': clean_acc,
            'masked_account': f'******{clean_acc[-4:]}',
            'ifsc_code': acc_data['ifsc_code'],
            'bank_name': acc_data['bank_name'],
            'branch_name': acc_data['branch_name'],
            'account_holder_name': acc_data['account_holder_name'],
            'account_type': acc_data['account_type'],
            'balance': float(acc_data['balance']),
            'is_active': acc_data['is_active'],
        }

    # 2. Check database BankAccounts table
    try:
        from portal.models.bank_accounts import BankAccounts
        from portal.helpers.encryption import decrypt

        candidates = BankAccounts.query.filter_by(
            account_last4=clean_acc[-4:],
            deleted_at=None,
        ).all() if len(clean_acc) >= 4 else []

        for cand in candidates:
            try:
                decrypted = decrypt(cand.account_number_enc)
                if decrypted == clean_acc:
                    if clean_ifsc and cand.ifsc_code.upper() != clean_ifsc:
                        continue

                    bank_meta = get_bank_info(cand.ifsc_code)
                    official_name = (
                        bank_meta['bank_name']
                        if bank_meta.get('ok')
                        else (cand.bank_name or 'Bank')
                    )

                    return {
                        'account_number': clean_acc,
                        'masked_account': f'******{cand.account_last4}',
                        'ifsc_code': cand.ifsc_code,
                        'bank_name': official_name,
                        'branch_name': cand.branch_name or bank_meta.get('branch', 'Main Branch'),
                        'account_holder_name': cand.verified_cbs_name or cand.account_holder_name or 'Account Holder',
                        'account_type': cand.account_type or 'SAVINGS',
                        'balance': float(cand.balance or Decimal('20000.00')),
                        'is_active': cand.is_active,
                    }
            except Exception:
                continue
    except Exception:
        pass

    return None


def validate_destination_account(account_no: str, ifsc: str) -> tuple[bool, str, dict | None]:
    """
    Validate that:
    1. Account number format is valid.
    2. IFSC format is valid.
    3. IFSC belongs to a supported institution.
    4. Account exists for that bank/institution in the test system.
    5. Account is active.
    """
    clean_acc = (account_no or '').strip().replace(' ', '')
    clean_ifsc = (ifsc or '').strip().upper()

    if not clean_acc or not clean_acc.isdigit() or not (6 <= len(clean_acc) <= 20):
        return False, 'Invalid bank account details. Please check the account number and IFSC code.', None

    bank_info = get_bank_info(clean_ifsc)
    if not bank_info.get('ok'):
        return False, bank_info.get('error', 'Invalid IFSC code.'), None

    account_info = lookup_test_account(clean_acc, clean_ifsc)
    if not account_info:
        return False, 'Bank account not found.', None

    if not account_info.get('is_active'):
        return False, 'This bank account is inactive.', None

    return True, 'Valid bank account.', account_info
