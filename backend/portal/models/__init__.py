from flask_migrate import Migrate

from portal import db

migrate = Migrate()


def init_app(app):
    migrate.init_app(app, db)

    app.logger.info("Initialized models")

    with app.app_context():
        # Import order matters: a model must be imported before anything that
        # declares a ForeignKey to it, or SQLAlchemy cannot resolve the string
        # target when it configures mappers.

        # -- Identity & access --------------------------------------------
        from .roles import Roles, RoleTypes
        from .users import Users, UserStatus, KYCTier
        from .user_profiles import UserProfiles
        from .user_security_settings import UserSecuritySettings
        from .user_sessions import UserSessions, SessionStatus
        from .device_bindings import DeviceBindings
        from .otp_verifications import OTPVerifications, OTPPurpose, OTPStatus
        from .login_history import LoginHistory, LoginStatus
        from .kyc_verifications import KYCVerifications, KYCStatus, DocumentType

        # -- Cards ---------------------------------------------------------
        from .card_networks import CardNetworks, NetworkType
        from .cards import Cards, CardStatus

        # -- Banking -------------------------------------------------------
        from .bank_accounts import BankAccounts, PennyDropStatus, AccountType
        from .penny_drop_verifications import PennyDropVerifications  # noqa: F401

        # -- Ledger (before anything that references a transaction) --------
        from .ledger_accounts import LedgerAccounts, AccountClass
        from .master_transactions import (
            MasterTransactions, TransactionType, TransactionStatus,
            SourceType, DestType, GatewayProvider, ReconStatus,
        )
        from .double_entry_ledger import DoubleEntryLedger

        # -- Throttling ----------------------------------------------------
        from .rate_limit_counters import RateLimitCounters  # noqa: F401

        # -- Credit line ---------------------------------------------------
        # Statements before transactions: a transaction carries a ForeignKey to
        # the statement it was billed on.
        from .credit_applications import (
            CreditApplications, ApplicationStatus, EmploymentType,
        )
        from .credit_accounts import (
            CreditAccounts, CreditAccountStatus, CreditPurpose,
        )
        from .credit_statements import CreditStatements, StatementStatus
        from .credit_transactions import (
            CreditTransactions, CreditTransactionType, CreditTransactionStatus,
            MerchantCategory,
        )

        # -- EMI -----------------------------------------------------------
        from .emi_providers import EMIProviders, ProviderIntegrationMode
        from .emi_obligations import (
            EMIObligations, LoanType, AutoPayStatus, EMIPaymentStatus,
        )
        from .emi_payments import EMIPayments, PaymentMode, EMIPaymentState
        from .auto_pay_mandates import (
            AutoPayMandates, MandateType, MandateStatus, MandateFrequency,
        )
        from .mandate_debit_attempts import MandateDebitAttempts, DebitAttemptResult

        # -- Platform ------------------------------------------------------
        from .notifications import (
            Notifications, NotificationPreferences, NotificationTemplates,
            NotificationChannel, NotificationPriority, NotificationEvent,
            DeliveryStatus,
        )
        from .domain_events import DomainEvents, EventStatus
        from .audit_logs import AuditLogs, AdminActivityLogs
        from .admin_settings import (
            AdminSettings, SettingDataType, FeatureFlags, FlagRolloutType,
        )
        from .reconciliation import (
            ReconciliationRuns, ReconciliationDiscrepancies,
            ReconRunStatus, DiscrepancyType, DiscrepancyResolution,
        )
        from .support_messages import (
            SupportTickets, SupportMessages, SupportSenderRole,
            TicketStatus, TicketCategory,
        )
        from .transaction_errors import (  # noqa: F401
            TransactionErrors, ErrorType,
        )
        from .qr_payments import QRPayments, QRPaymentState  # noqa: F401
        from .platform_statistics import PlatformStatistics
