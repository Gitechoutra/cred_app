"""
Automated Test Suite for Card-to-Bank Transfer and Balance Logic.

Tests:
1. Successful transfer balance update:
   - Source card balance deducted by transfer amount
   - Destination bank account balance increased by transfer amount
   - Balance snapshot recorded (opening and closing balances)
2. Insufficient card balance validation:
   - Attempting transfer exceeding available_limit fails with "Insufficient card balance."
3. Centralized IFSC lookup:
   - Valid IFSC (e.g. SBIN0001234, HDFC0000001, BAJF0000001) resolves authoritative institution name
4. Invalid IFSC validation:
   - Invalid format or unknown bank code returns "Invalid IFSC code."
5. Test account lookup validation:
   - Valid IFSC + known test account returns verified bank details & balance
   - Valid IFSC + non-existent test account returns "Bank account not found."
6. Balance persistence across fresh queries / sessions:
   - Balances remain correct in MySQL DB after re-querying
7. Idempotency:
   - Duplicate transfer request with same idempotency_key returns original transfer without double deduction
8. Atomicity & rollback:
   - If settlement encounters an exception, neither card nor bank balance changes
"""

import os
import sys
import uuid
from decimal import Decimal
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from portal.models.base import db
from portal.models.users import Users
from portal.models.cards import Cards
from portal.models.bank_accounts import BankAccounts
from portal.models.transfers import Transfers
from portal.helpers import bank_ifsc_service, transfer_engine
from portal.helpers.transfer_engine import TransferError


def run_tests():
    with app.app_context():
        print("=" * 70)
        print("RUNNING CARD-TO-BANK TRANSFER & BALANCE VERIFICATION SUITE")
        print("=" * 70)
        
        # Setup Test User
        user = Users.query.filter_by(user_id='ea391d54-0093-4c64-8628-40c370c75af6').first()
        assert user is not None, "Test user not found"
        user_id = user.user_id
        
        # Reset recent transfers to prevent rate limiting
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        Transfers.query.filter(
            Transfers.user_id == user_id,
            Transfers.created_on > two_hours_ago
        ).update({'created_on': two_hours_ago - timedelta(minutes=15)})
        db.session.commit()
        
        card = Cards.query.filter_by(user_id=user_id, status='ACTIVE').first()
        bank = BankAccounts.query.filter_by(user_id=user_id).first()
        assert card is not None, "Active card not found"
        assert bank is not None, "Active bank account not found"
        
        # Set known baseline balances
        card.available_limit = Decimal('50000.00')
        card.outstanding_amount = Decimal('0.00')
        bank.balance = Decimal('20000.00')
        db.session.commit()
        
        print(f"Initial State -> Card Available: INR {card.available_limit}, Bank Balance: INR {bank.balance}")

        # -------------------------------------------------------------------------
        # TEST 1: Successful Transfer Balance Update
        # -------------------------------------------------------------------------
        print("\n[TEST 1] Successful Transfer Balance Update (INR 50,000 -> Transfer INR 5,000)")
        transfer_amount = Decimal('5000.00')
        idem_key_1 = f"test-idem-{uuid.uuid4().hex[:12]}"
        
        transfer_result = transfer_engine.initiate(
            user_id=user_id,
            card_id=card.card_id,
            bank_account_id=bank.bank_account_id,
            amount=transfer_amount,
            mode='IMPS',
            ip_address='127.0.0.1',
            user_agent='pytest-test-runner',
            idempotency_key=idem_key_1
        )
        
        # Refresh from DB
        db.session.expire_all()
        card_after = Cards.query.get(card.card_id)
        bank_after = BankAccounts.query.get(bank.bank_account_id)
        transfer_record = Transfers.query.get(transfer_result['transfer_id'])
        
        print(f"  Result Transfer ID: {transfer_record.id}, Status: {transfer_record.status}")
        print(f"  Card Available Limit: INR {card_after.available_limit} (Expected: INR 45000.00)")
        print(f"  Bank Account Balance: INR {bank_after.balance} (Expected: INR 25000.00)")
        print(f"  Transfer Snapshot -> Source: INR {transfer_record.source_opening_balance} -> INR {transfer_record.source_closing_balance}")
        print(f"  Transfer Snapshot -> Dest: INR {transfer_record.destination_opening_balance} -> INR {transfer_record.destination_closing_balance}")
        
        assert card_after.available_limit == Decimal('45000.00'), f"Expected 45000.00, got {card_after.available_limit}"
        assert bank_after.balance == Decimal('25000.00'), f"Expected 25000.00, got {bank_after.balance}"
        assert transfer_record.source_opening_balance == Decimal('50000.00')
        assert transfer_record.source_closing_balance == Decimal('45000.00')
        assert transfer_record.destination_opening_balance == Decimal('20000.00')
        assert transfer_record.destination_closing_balance == Decimal('25000.00')
        print("  >>> TEST 1 PASSED: Transferred amount accurately deducted from card and added to bank account.")

        # -------------------------------------------------------------------------
        # TEST 2: Insufficient Card Balance Rejection
        # -------------------------------------------------------------------------
        print("\n[TEST 2] Insufficient Card Balance Rejection")
        card_after.available_limit = Decimal('3000.00')
        db.session.commit()
        
        # Reset rate limits
        Transfers.query.filter(Transfers.user_id == user_id).update({'created_on': two_hours_ago})
        db.session.commit()
        
        excessive_amount = Decimal('5000.00')
        try:
            transfer_engine.initiate(
                user_id=user_id,
                card_id=card.card_id,
                bank_account_id=bank.bank_account_id,
                amount=excessive_amount,
                mode='IMPS',
                ip_address='127.0.0.1',
                user_agent='pytest-test-runner',
                idempotency_key=f"test-idem-{uuid.uuid4().hex[:12]}"
            )
            assert False, "Transfer should have failed with Insufficient card balance"
        except TransferError as e:
            print(f"  Caught expected error: {e.message}")
            assert e.message == "Insufficient card balance.", f"Unexpected message: {e.message}"
            print("  >>> TEST 2 PASSED: Transfer rejected with 'Insufficient card balance.'")

        # -------------------------------------------------------------------------
        # TEST 3: Centralized IFSC Resolution (Banks & NBFCs)
        # -------------------------------------------------------------------------
        print("\n[TEST 3] Centralized IFSC Resolution")
        test_ifscs = [
            ("SBIN0001234", "State Bank of India (SBI)"),
            ("HDFC0000001", "HDFC Bank"),
            ("ICIC0001000", "ICICI Bank"),
            ("UTIB0000123", "Axis Bank"),
            ("KKBK0000456", "Kotak Mahindra Bank"),
            ("BAJF0000001", "Bajaj Finance Limited"),
            ("PYTM0123456", "Paytm Payments Bank"),
        ]
        for ifsc, expected_name in test_ifscs:
            info = bank_ifsc_service.get_bank_info(ifsc)
            assert info['is_valid'] is True
            assert info['bank_name'] == expected_name, f"Expected {expected_name}, got {info['bank_name']}"
            print(f"  IFSC {ifsc} -> '{info['bank_name']}' (Category: {info['category']})")
        print("  >>> TEST 3 PASSED: All major banks and financial institutions correctly identified.")

        # -------------------------------------------------------------------------
        # TEST 4: Invalid IFSC Code Validation
        # -------------------------------------------------------------------------
        print("\n[TEST 4] Invalid IFSC Code Validation")
        invalid_ifscs = ["INVALID123", "SBIN01", "ZZZZ0001234", "12345678901"]
        for bad_ifsc in invalid_ifscs:
            info = bank_ifsc_service.get_bank_info(bad_ifsc)
            assert info['is_valid'] is False
            print(f"  Invalid IFSC '{bad_ifsc}' rejected -> is_valid=False")
        
        val_res, val_msg = bank_ifsc_service.validate_account_details("ZZZZ0001234", "123456789012")
        assert val_res is False
        assert val_msg == "Invalid IFSC code."
        print(f"  Account validation error message: '{val_msg}'")
        print("  >>> TEST 4 PASSED: Invalid IFSC code properly rejected.")

        # -------------------------------------------------------------------------
        # TEST 5: Test Account Lookup & Non-existing Rejection
        # -------------------------------------------------------------------------
        print("\n[TEST 5] Test Account Lookup & Non-Existing Rejection")
        # Existing test account lookup
        test_acc = bank_ifsc_service.lookup_test_account("SBIN0001234", "987654321012")
        assert test_acc is not None
        assert test_acc['bank_name'] == "State Bank of India (SBI)"
        assert test_acc['account_holder_name'] == "LINGAM REVANTH"
        assert test_acc['balance'] == Decimal('25000.00')
        print(f"  Lookup Known Test Account: {test_acc['bank_name']} | Holder: {test_acc['account_holder_name']} | Balance: INR {test_acc['balance']}")
        
        # Non-existing account lookup
        test_non_existent = bank_ifsc_service.lookup_test_account("SBIN0001234", "000000000000")
        assert test_non_existent is None
        val_res_ne, val_msg_ne = bank_ifsc_service.validate_account_details("SBIN0001234", "000000000000")
        assert val_res_ne is False
        assert val_msg_ne == "Bank account not found."
        print(f"  Non-existing Account rejected with: '{val_msg_ne}'")
        print("  >>> TEST 5 PASSED: Valid and non-existing accounts handled with expected messages.")

        # -------------------------------------------------------------------------
        # TEST 6: Persistence Across DB Reload
        # -------------------------------------------------------------------------
        print("\n[TEST 6] Persistence Across Database Reload")
        db.session.close()  # Close session completely to simulate restart
        
        # Fresh query from database engine
        card_reloaded = db.session.query(Cards).filter_by(card_id=card.card_id).one()
        bank_reloaded = db.session.query(BankAccounts).filter_by(bank_account_id=bank.bank_account_id).one()
        print(f"  Reloaded from DB -> Card Available: INR {card_reloaded.available_limit}, Bank Balance: INR {bank_reloaded.balance}")
        assert card_reloaded.available_limit == Decimal('3000.00')
        assert bank_reloaded.balance == Decimal('25000.00')
        print("  >>> TEST 6 PASSED: Balances are fully persistent in MySQL database.")

        # -------------------------------------------------------------------------
        # TEST 7: Idempotency & Duplicate Submission
        # -------------------------------------------------------------------------
        print("\n[TEST 7] Idempotency & Duplicate Submission")
        # Give card sufficient limit
        card_reloaded.available_limit = Decimal('50000.00')
        db.session.commit()
        
        # Reset hourly rate limits
        Transfers.query.filter(Transfers.user_id == user_id).update({'created_on': two_hours_ago})
        db.session.commit()
        
        duplicate_idem_key = f"test-idem-dup-{uuid.uuid4().hex[:8]}"
        res1 = transfer_engine.initiate(
            user_id=user_id,
            card_id=card.card_id,
            bank_account_id=bank.bank_account_id,
            amount=Decimal('1000.00'),
            mode='IMPS',
            ip_address='127.0.0.1',
            user_agent='pytest-test-runner',
            idempotency_key=duplicate_idem_key
        )
        balance_after_res1 = Cards.query.get(card.card_id).available_limit
        assert balance_after_res1 == Decimal('49000.00')
        
        # Second call with the same idempotency key
        res2 = transfer_engine.initiate(
            user_id=user_id,
            card_id=card.card_id,
            bank_account_id=bank.bank_account_id,
            amount=Decimal('1000.00'),
            mode='IMPS',
            ip_address='127.0.0.1',
            user_agent='pytest-test-runner',
            idempotency_key=duplicate_idem_key
        )
        balance_after_res2 = Cards.query.get(card.card_id).available_limit
        assert res1['transfer_id'] == res2['transfer_id'], "Should return identical transfer record"
        assert balance_after_res2 == Decimal('49000.00'), "Balance should NOT be deducted twice"
        print(f"  First call Transfer ID: {res1['transfer_id']}, Second call Transfer ID: {res2['transfer_id']}")
        print(f"  Card balance remained INR {balance_after_res2} (no double deduction)")
        print("  >>> TEST 7 PASSED: Idempotency verified, duplicate submission handled safely.")

        # -------------------------------------------------------------------------
        # TEST 8: Failure Rollback & Atomicity
        # -------------------------------------------------------------------------
        print("\n[TEST 8] Failure Rollback & Atomicity")
        # Temporarily mock _payout to fail and verify neither balance changes
        card_before_fail = Cards.query.get(card.card_id).available_limit
        bank_before_fail = BankAccounts.query.get(bank.bank_account_id).balance
        
        from portal.helpers import payout_adapter
        original_disburse = payout_adapter.disburse
        
        def failing_disburse(*args, **kwargs):
            raise RuntimeError("Simulated partner bank network error during payout")
        
        payout_adapter.disburse = failing_disburse
        try:
            transfer_engine.initiate(
                user_id=user_id,
                card_id=card.card_id,
                bank_account_id=bank.bank_account_id,
                amount=Decimal('2000.00'),
                mode='IMPS',
                ip_address='127.0.0.1',
                user_agent='pytest-test-runner',
                idempotency_key=f"test-idem-fail-{uuid.uuid4().hex[:8]}"
            )
            assert False, "Should have failed due to simulated network error"
        except Exception as e:
            print(f"  Caught simulated error: {e}")
        finally:
            payout_adapter.disburse = original_disburse
            db.session.rollback()
        
        # Verify balances were NOT changed
        card_after_fail = Cards.query.get(card.card_id).available_limit
        bank_after_fail = BankAccounts.query.get(bank.bank_account_id).balance
        print(f"  Card Available before: INR {card_before_fail}, after: INR {card_after_fail}")
        print(f"  Bank Balance before: INR {bank_before_fail}, after: INR {bank_after_fail}")
        assert card_before_fail == card_after_fail, "Card balance changed during failed transfer!"
        assert bank_before_fail == bank_after_fail, "Bank balance changed during failed transfer!"
        print("  >>> TEST 8 PASSED: Atomicity verified, database changes rolled back cleanly on error.")

        # Clean up baseline balance for test user
        card_obj = Cards.query.get(card.card_id)
        card_obj.available_limit = Decimal('50000.00')
        card_obj.outstanding_amount = Decimal('0.00')
        bank_obj = BankAccounts.query.get(bank.account_id)
        bank_obj.balance = Decimal('20000.00')
        db.session.commit()
        print("\nRestored baseline balances for user Lingam Revanth.")
        print("=" * 70)
        print("ALL 8 TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

if __name__ == '__main__':
    run_tests()
