  # CashU — Version 1 Specification

  > **Derived from:** Project Requirement Document (PRD) v1.0.0-PROD-SPEC —
  > *"CredFlow / Unified Credit & EMI Management Platform"*, working title `cred_v1`.
  > **This document:** v1 build specification · **Revision 2** · **Date:** 2026-09-28 · **Owner:** Mahesh
  > **Reflects code at:** branch `cashu`, commit `a1d426c`
  >
  > The PRD is the source of truth for *what* CashU is. This document is the source of
  > truth for *how v1 gets built* on the chosen stack — it takes the PRD's P0 slice and
  > maps it onto a Flask/MySQL monolith following the stockverse house structure.
  >
  > Where this document departs from the PRD, the departure is marked **⚑ DEVIATION**
  > with the reason. Nothing is silently dropped.

  ### Revision log

  | Rev | Date | Change |
  |---|---|---|
  | 1 | 2026-09-09 | Initial v1 specification from the PRD P0 slice. |
  | 2 | 2026-09-28 | **Product pivot.** Credit-to-bank transfer (FR-006) removed (`5b64317`). Replaced by a **CashU-issued credit line**: apply → KYC → review → purpose → activate → spend → statement → bill pay → credit restored (`0f20029`, `ef02c50`, `28c6286`, `f182906`, `a1d426c`). Added Scan & Pay (UPI QR), Razorpay as the collection rail, the transaction-error centre and support assistant. Sections 1, 2, 5, 6, 7, 8, 9, 10, 12–17 updated to match the code. |

  ---

  ## 1. Product identity

  | Attribute | Value |
  |---|---|
  | Product name | **CashU** |
  | PRD codename | CredFlow / Unified Credit & EMI Hub (`cred_v1`) |
  | Market | India (INR only, domestic cards and banks) |
  | Release | Version 1.0 — MVP, production-intent |
  | Delivery | **Responsive web app** (desktop sidebar layout, drawer + bottom nav below `lg`) |
  | Regulatory posture | RBI Credit Card Master Direction · DPDPA 2023 · PCI DSS v4.0 SAQ-A · PMLA · NPCI e-Mandate · NPCI UPI |

  **One line:** CashU gives a user their own CashU credit line (a RuPay card), puts it
  next to their other credit cards and NBFC loan EMIs on one dashboard, and lets them
  pay every one of those obligations — card bill, EMI, auto-pay — without visiting six
  banking portals.

  **What CashU is not.** Not a rewards or cashback app. Not a wallet — CashU holds no
  customer funds. **It does not move credit into a bank account** — that product was
  removed on 2026-09-24. Not a card issuer or lender *in its own right*: the credit line
  must be issued through a licensed lending/issuing partner (see §16, decision 1).

  ---

  ## 2. The three pillars of v1

  Everything in v1 serves one of three jobs. If a proposed feature serves none, it is
  out of scope.

  | Pillar | User job | Anchor requirements |
  |---|---|---|
  | **1. See** | "Show me everything I owe, in one place, without anxiety." | FR-002 dashboard, FR-003 external card tracking, FR-004 card detail, FR-007 EMI registry, CashU card home |
  | **2. Service** | "Let me pay what's due without hunting for a portal." | FR-008 manual EMI pay, FR-009 auto-pay mandates, **credit line bill payment** |
  | **3. Credit** *(was "Access")* | "Give me a credit line I can apply for, understand, and spend responsibly." | **Credit line lifecycle** (apply, decision, purpose, activate, spend, statements), Scan & Pay |

  Underneath all three: FR-001 identity, FR-005 bank-account verification, FR-010
  ledger, FR-011 notifications, FR-012 profile/KYC/security.

  > ⚑ **DEVIATION — Pillar 3.** The PRD's "Access" pillar was FR-006 credit-to-bank
  > transfer. It was removed because RBI's Credit Card Master Direction treats
  > credit-to-bank movement as disguised cash cycling and PRD open decision #1 (the
  > merchant model) was never resolved. The credit line only funds **merchant
  > purchases**, which is what a card is licensed to do.

  ---

  ## 3. Brand & UI direction

  The PRD specifies function, not visual identity. This section is the design contract.

  ### 3.1 Palette

  | Token | Value | Role |
  |---|---|---|
  | `--cashu-mint` | `#00F5B8` | **Primary accent** — CTAs, active states, positive deltas, focus rings |
  | `--cashu-canvas` | `#FFFFFF` | **Primary background** |
  | `--cashu-ink` | `#0A0F0D` | Primary text; dark surfaces (card tiles, the card face) |
  | `--cashu-mist` | `#F4F6F5` | Secondary surfaces, input fills, skeletons |
  | `--cashu-line` | `#E6EAE8` | Hairlines, dividers, card borders |
  | `--cashu-slate` | `#6B7674` | Secondary text, captions, disabled |
  | `--cashu-alert` | `#EF4444` | Overdue, failed, destructive — **PRD §FR-002 specifies this exact hex** |
  | `--cashu-warn` | `#F59E0B` | Due within 3 days, pending, under review |

  **Rules.**
  - White dominates. Mint is punctuation — never a large fill, never body text on white
    (it fails WCAG AA below 18px). Mint chips carry `--cashu-ink` text.
  - Utilization meter is the one place colour encodes data: mint ≤30%, slate 30–60%,
    warn 60–80%, alert >80%. Never green-to-red gradient — it reads as judgement.
  - Overdue states use `--cashu-alert` on a white ground, never a red fill. This is a
    debt app; a wall of red is hostile.

  ### 3.2 Motion & tone

  Premium here means *calm*, not flashy. Money numbers animate once on load
  (count-up, 400ms, ease-out) and never again. State transitions are 150–200ms.
  The payment result (receipt) screen is the single "moment" — animated
  success / failure / pending — everything else is quiet.

  **Type.** One geometric sans. All monetary values in tabular-lining numerals so digits
  don't jitter during count-up or live refresh.

  **Copy.** Never scold. "₹4,250 due in 3 days" — not "You're late." Failure messages
  state the cause and the next action, per the PRD §20 user-facing message column.
  A credit balance reads **"Credit ₹X"**, never a negative "Used".

  ### 3.3 Navigation

  - Primary nav (5 items, fits 320px): **Home · Cards · Scanner · Search · History**.
    Profile menu: Profile, Security, Bank accounts, Help & support, Operations console
    (admins only), Logout.
  - **Back buttons go through `useNavHistory`** (`useBack` / `useReturnTo`). `back()`
    goes to the real previous screen and falls back to the page's parent only when
    there is none. A string `back` on `PageHeader` is a fallback, never a destination.
    Hard-coded back paths are not allowed.
  - Multi-step screens keep the step in the URL so browser back walks the steps, and
    drafts survive leaving and returning. A finished flow uses `returnTo()` so
    completed steps drop off the history stack.
  - Every screen has loading, empty and error states.

  ### 3.4 Logo

  **Concept — "The Coin Cut."** A `U` drawn as the lower arc of a coin, its negative
  space cutting an upward notch: reads simultaneously as currency and as headroom
  recovered. Mint on white, ink on mint, single-colour safe, legible at 16px.

  Alternates: monogram `C` whose counter forms a `U`; a rupee stroke integrated into the
  `U` stem; wordmark with one mint accent letter.

  Deliverables: app icon (1024/512/192/32), horizontal lockup, monochrome, favicon,
  splash mark.

  ---

  ## 4. Target users

  From PRD §4, re-weighted for the credit-line product.

  | Persona | Who | What v1 gives them |
  |---|---|---|
  | **Multi-Card Maximizer** *(primary)* | 26–42, salaried, 3–6 cards, ₹8L–₹30L p.a. | Aggregate limit, utilization warning, unified due calendar, a CashU card alongside the rest |
  | **Consumer EMI Repayer** *(primary)* | 22–48, consumer-durable / two-wheeler loans via Bajaj, HDB, IDFC | Biller discovery, one-tap UPI payment, auto-pay scheduling |
  | **First-Line Credit Seeker** *(secondary, replaces "Emergency Liquidity Seeker")* | Salaried or self-employed, wants a transparent credit line with a declared purpose | Instant indicative offer, clear decision reasons, statements with minimum due |
  | **Ops & Compliance Staff** *(internal)* | Risk analysts, support, settlement accountants | RBAC console, credit application queue, KYC queue, immutable audit trail, recon dashboard |

  ---

  ## 5. Scope boundary

  ### 5.1 In — v1.0 (as built)

  | # | Capability | Ref | Status |
  |---|---|---|---|
  | 1 | Mobile + OTP authentication, 6-digit MPIN, device binding, sessions | FR-001 | ✅ Built |
  | 2 | Home hub + dashboard — aggregate limit, utilization, nearest due | FR-002 | ✅ Built |
  | 3 | External credit card tracking (BIN + last 4 only), masked display | FR-003 | ✅ Built — **tracking only**, no bill-pay rail for external cards |
  | 4 | Card detail, billing cycle config, unlink | FR-004 | ✅ Built |
  | 5 | Bank account linking with penny-drop name verification + IFSC lookup | FR-005 | ✅ Built |
  | 6 | ~~Credit-facility → bank transfer~~ | FR-006 | ❌ **Removed 2026-09-24** |
  | 7 | EMI obligation registry (Bajaj Finance anchor adapter) + sanction-letter upload | FR-007 | ✅ Built |
  | 8 | Manual EMI payment via UPI / netbanking / debit card (Razorpay) | FR-008 | ✅ Built |
  | 9 | Recurring auto-pay via NPCI e-Mandate / UPI AutoPay | FR-009 | ✅ Built (sandbox rail) |
  | 10 | Double-entry immutable ledger + transaction history | FR-010 | ✅ Built |
  | 11 | Notification & alert engine (SMS/Email/In-App) | FR-011 | ⚠ Partial — credit-line events do not notify yet (§11) |
  | 12 | Profile, KYC tiering, security settings, data export, erasure | FR-012 | ✅ Built |
  | 13 | RBAC admin & operations console | §15, §16 | ✅ Built |
  | 14 | **CashU credit line** — apply, decision, purpose, activate, spend, statements, bill pay, refunds, block | New | ✅ Built |
  | 15 | **Scan & Pay** — scan a UPI QR, pay the merchant from the user's bank via UPI | New | ✅ Built |
  | 16 | **Transaction-error centre + support assistant** — every failed payment recorded with a reason; scripted, transaction-aware help; ticket escalation | New | ✅ Built |

  ### 5.2 Deferred — explicitly not v1

  | Deferred to | Items |
  |---|---|
  | **Phase 1.1 (P1)** | Push via FCM/APNS, additional EMI providers (HDB, IDFC), smart auto-pay retries, biometric unlock, credit-line notifications |
  | **Phase 2.0 (P2)** | Account Aggregator statement sync, credit score tracking (CIBIL/Experian), interest on revolving balances |
  | **Phase 3.0 (P3)** | Card reward-points optimization, split-card payments |
  | **Never (non-goals)** | Credit-to-bank transfers, P2P money laundering / cash cycling, crypto, raw PAN/CVV/PIN storage, unlicensed P2P lending, physical POS, paying a loan EMI with credit |

  > **Note.** Rewards, coins, cashback, and a user wallet are **not** part of CashU.
  > CashU never holds customer funds.

  ---

  ## 6. Stack & the PRD deviations

  ### 6.1 Chosen stack

  | Layer | Choice |
  |---|---|
  | Frontend | React.js + Tailwind CSS + Vite (dev server on :3000) |
  | Backend | Python 3.12 · Flask · flask-restx · Flask-SQLAlchemy · Flask-Migrate |
  | Database | **MySQL 8.4** (InnoDB, utf8mb4) |
  | Auth | flask-jwt-extended |
  | Scheduler | APScheduler (IST cron triggers) |
  | Collection rail | **Razorpay** — Checkout for UPI, Google Pay / PhonePe / Paytm, net banking, debit card |
  | Verification rail | **Cashfree** — penny drop, IFSC verification |
  | Container | Docker + docker compose |

  ### 6.2 ⚑ DEVIATIONS from PRD infrastructure

  The PRD specifies enterprise infrastructure appropriate to a funded, licensed
  operation. v1 is built as a modular monolith on the chosen stack. Each deviation
  below is deliberate, with the mitigation named.

  | # | PRD specifies | v1 does | Consequence & mitigation |
  |---|---|---|---|
  | **D1** | PostgreSQL | **MySQL 8.4** | Ledger integrity preserved via InnoDB + explicit `REPEATABLE READ` transactions with `SELECT … FOR UPDATE` on balance-affecting rows. **Every locking read uses `populate_existing()`** — without it SQLAlchemy takes the lock and then keeps the stale, pre-lock attributes from its identity map (found by `credit_concurrency.py`: 5 of 6 concurrent purchases were lost before the fix). |
  | **D2** | Redis (OTP hash 180s TTL, sliding-window rate limits, 24h idempotency keys) | **MySQL tables + APScheduler sweeps** | `otp_verifications` carries `expires_at`; rate limits are `rate_limit_counters` rows on a time bucket; **idempotency is a `UNIQUE` index** on `master_transactions`, `credit_transactions` and `qr_payments` — a duplicate insert raises `IntegrityError` and the original is returned. A janitor job purges expired rows. |
  | **D3** | Microservices on Kubernetes/EKS with HPA | **Modular Flask monolith** | Each PRD "service" is an *engine module* in `portal/helpers/` with a defined interface. Extraction later is a deployment change, provided no engine reaches into another's tables directly. |
  | **D4** | Kafka / RabbitMQ event bus with outbox | **In-process domain events + APScheduler workers** | A `domain_events` table plays the outbox role; the scheduler drains it every minute. |
  | **D5** | React Native (iOS/Android) + Next.js | **React + Vite responsive web** | Web application with a persistent sidebar, top bar and multi-column layouts; drawer + bottom nav below `lg`. Native shell is post-v1. |
  | **D6** | Integer autoincrement (stockverse house style) | **UUIDv4 primary keys** on financial entities | Stored `CHAR(36)`. Lookup tables (`roles`, `providers`) keep integer PKs. Credit transactions additionally carry a quotable `CCT…` reference. |
  | **D7** | Multi-AZ, 99.95% SLA, PITR, WORM audit storage | Single-node dev/staging | Deferred until a licensed partner is signed. Audit rows are append-only *by application rule*. |
  | **D8** | FR-006 credit-to-bank transfer | **Removed; replaced by an issued credit line** | See §2. Settled transfers remain in `master_transactions` / `double_entry_ledger` (append-only); `CARD_TO_BANK_TRANSFER` stays a valid type so those rows still validate. |

  ### 6.3 What these deviations cost

  **D1 and D2 are the ones that can bite.** The ledger's correctness depends on
  discipline in application code. Mitigations: every money path goes through
  `ledger_engine.post()`; every credit-line balance goes through `credit_engine`; each
  balance change asserts `available_credit + current_outstanding == credit_limit`
  before commit; a nightly self-audit asserts debits equal credits and that derived
  balances match ledger sums; statement cut logs any closing balance that disagrees
  with what the account owes.

  ---

  ## 7. Architecture

  ### 7.1 Repository layout

  ```
  CashU/
  ├── backend/                          Flask API — mirrors stockverse
  │   ├── app.py                        entry point; create_all + seeders; port 5050
  │   ├── config/                       config.py (Dev / Testing / Production) + *.ini
  │   ├── portal/
  │   │   ├── __init__.py               InitApp class, APP singleton, db = SQLAlchemy()
  │   │   ├── extensions.py · logger.py · scheduler.py
  │   │   ├── api/__init__.py           flask-restx Api on the /v1 blueprint
  │   │   ├── helpers/                  the engines — see §7.2
  │   │   ├── models/                   one model per file
  │   │   ├── routes/                   one package per namespace (§9)
  │   │   ├── seeders/                  roles, admin, settings, flags, ledger accounts,
  │   │   │                             card networks, EMI providers, notification templates
  │   │   └── uploads/                  KYC documents, loan sanction letters
  │   ├── migrations/                   Flask-Migrate
  │   ├── tests/                        integration suites + run_all.py (§17.2)
  │   └── requirements.txt · Dockerfile · docker-entrypoint.sh · .env.example
  │
  ├── frontend/                         React + Vite + Tailwind
  │   ├── src/
  │   │   ├── app/App.jsx               route table
  │   │   ├── components/               ui primitives, layout (AppShell, BottomNav), domain rows
  │   │   ├── pages/
  │   │   │   ├── auth/                 splash, phone, OTP, MPIN, profile setup, admin login
  │   │   │   ├── user/                 hub, dashboard, cards, banks, EMI, scan, transactions, profile, KYC, support
  │   │   │   ├── credit/               apply, status, purpose, activate, home, spend, pay bill, transactions, statements
  │   │   │   └── admin/                dashboard, users, KYC queue, reconciliation, settings
  │   │   ├── context/  hooks/ (useNavHistory, useProfile, useReveal)  api/  utils/  styles/
  │   ├── scripts/ui-audit.mjs          static UI audit (routes, nav targets)
  │   └── Dockerfile · nginx.conf
  │
  ├── docker-compose.yml                MySQL 8.4 + backend + frontend
  └── Version1.md                       this document
  ```

  ### 7.2 Engines — `portal/helpers/`

  | Area | Module | Responsibility |
  |---|---|---|
  | Auth | `jwt.py`, `otp.py`, `rate_limit.py` | Token issue/rotate, OTP lifecycle, throttles |
  | **Credit line** | `credit_engine.py` | **The only writer of credit limit, available credit and outstanding.** Assess, decide, issue, purpose, activate, block, purchase, bill payment open/settle/cancel/poll, statement cut, overdue + late fee, refund |
  | EMI | `emi_engine.py`, `emi_provider_adapter.py`, `emi_fees.py` | FR-008 lifecycle, biller lookup, mandate cap (≥110% of EMI) |
  | Auto-pay | `mandate_engine.py` | e-Mandate registration, pre-debit notices, execution, retry ladder |
  | Scan & Pay | `qr_payment_engine.py`, `upi_qr.py` | Strict UPI deep-link parsing; collect over UPI, confirm from gateway |
  | Ledger | `ledger_engine.py` | **The only writer of ledger rows.** Post, reverse, reconcile, self-audit |
  | Rails | `adapters.py`, `razorpay.py`, `cashfree.py` | Vendor seams; sandbox vs live selection; signature verification |
  | Bank accounts | `name_match.py`, `bank_ifsc_service.py` | Penny-drop name similarity, IFSC → bank/branch |
  | Notifications | `notify.py`, `sms.py`, `email.py` | Channel routing per §11 |
  | Errors & support | `error_catalog.py`, `error_recorder.py`, `support_bot.py` | Record every failed payment with a cause; scripted, transaction-aware assistant |
  | Platform | `audit.py`, `encryption.py`, `validators.py`, `settings.py`, `test_cards.py` | Audit writes, AES-256-GCM PII, input validation, admin settings with defaults, dev-only test cards |

  **Removed with FR-006:** `transfer_engine.py`, `fee_calculator.py`, `risk_engine.py`.

  **Hard rules.**
  - `ledger_engine.post()` is the sole entry point for any ledger row.
  - `credit_engine` is the sole writer of credit balances. No route computes a balance
    and no request parser accepts one.

  ### 7.3 Scheduled jobs (`scheduler.py`, all times IST)

  | Job | Cadence | Purpose |
  |---|---|---|
  | `payment_status_poll` | every 15 min | Poll PENDING EMI / QR payments up to 24h |
  | `credit_bill_payment_poll` | every 2 min | Settle PROCESSING credit bill payments from the gateway; close unpaid ones after 30 min |
  | `domain_event_drain` | every 1 min | Outbox → notification dispatch (⚑ D4) |
  | `credit_statement_cut` | daily 00:20 | Cut statements whose cycle day is today |
  | `credit_overdue_sweep` | daily 01:00 | Mark past-due statements OVERDUE; charge late fee once |
  | `mandate_execute` | daily 04:00 | Trigger due mandate debits |
  | `mandate_predebit_notice` | daily 10:00 | T-48h pre-debit notice — **regulatory, non-negotiable** |
  | `mandate_retry_midday` / `_evening` | 11:30 / 18:00 | Retry ladder attempts 2 and 3 |
  | `ledger_self_audit` | daily 02:30 | Assert debits == credits; flag drift (⚑ D1) |
  | `emi_due_reminder` | daily 09:00 | Flags overdue EMIs (despite the name, sends no T-7/T-1 reminder — see §11) |
  | `janitor` | hourly | Purge expired OTP + rate-limit rows (⚑ D2) |

  Removed: `transfer_recon`, `token_expiry_sweep`.

  ---

  ## 8. Data model

  Stockverse house style: plural class names, sibling status-constant classes,
  `created_on` / `updated_on`, `save()` / `update()` helpers. Money is `Numeric(12,2)`.
  Timestamps are UTC and serialised with an explicit offset. Credit transactions use
  `DATETIME(6)` so two rows in the same second still order correctly.

  ### 8.1 Identity & access

  `Roles` (`NORMAL_USER`, `L1_SUPPORT`, `L2_RISK_RECON`, `L3_SUPER_ADMIN`) · `Users`
  (`kyc_tier` NONE/MINIMUM/FULL, `mpin_hash`) · `UserProfiles` · `UserSessions` ·
  `OTPVerifications` · `LoginHistory` · `UserSecuritySettings` · `KYCVerifications` ·
  `DeviceBindings` · `RateLimitCounters`

  ### 8.2 External cards & banking

  | Model | Notes |
  |---|---|
  | `Cards` | External cards the user tracks: BIN, `masked_pan`, issuer, network, limit, due day. **Never a PAN, CVV, or PIN column.** |
  | `CardNetworks` | Visa / Mastercard / RuPay / Amex reference + BIN routing |
  | `BankAccounts` | `account_number_enc`, IFSC, bank name, `verified_cbs_name`, penny-drop status, `is_primary` |
  | `PennyDropVerifications` | IMPS ref, CBS name returned, similarity score, decision |

  ### 8.3 CashU credit line *(new)*

  | Model | Notes |
  |---|---|
  | `CreditApplications` | employment type, monthly income, existing EMI outflow, requested / offered / approved limit, eligibility score, `decision_reason`, `ApplicationStatus` |
  | `CreditAccounts` | card BIN + last 4 only (RuPay), name on card, expiry, `credit_limit`, `available_credit`, `current_outstanding`, `purpose` (+ note for OTHER), `statement_day`, `grace_days`, `CreditAccountStatus` |
  | `CreditTransactions` | **Append-only.** PURCHASE / PAYMENT / REFUND / FEE; amount, `balance_after`, `available_after`, merchant + category, `idempotency_key` (UNIQUE), `statement_id`, payment method + gateway ids, `failure_code/reason`, `is_test` |
  | `CreditStatements` | **Append-only.** period, opening / purchases / payments / refunds / fees / closing, `minimum_due`, `total_amount_due`, limit + available at close, `amount_paid`, `StatementStatus`, `late_fee_charged_at`. UNIQUE (`credit_account_id`, `period_end`) |

  ### 8.4 EMI

  `EMIProviders` · `EMIObligations` (matches PRD §10.2) · `EMIPayments` ·
  `AutoPayMandates` · `MandateDebitAttempts`

  ### 8.5 Scan & Pay *(new)*

  `QRPayments` — payee VPA + name, amount (and whether it came from the QR), note,
  `idempotency_key` (UNIQUE), gateway order/payment ids, UPI RRN, payer VPA,
  `QRPaymentState` (INITIATED → PROCESSING → SUCCESSFUL / PENDING / FAILED / CANCELLED).

  ### 8.6 Ledger & money (the core)

  | Model | Notes |
  |---|---|
  | `MasterTransactions` | PRD §13.1: type, gross/net/fee/tax, source/dest, `gateway_provider` (CASHFREE / RAZORPAY / SANDBOX / **INTERNAL**), refs, `idempotency_key` (UNIQUE), status, `recon_status` |
  | `DoubleEntryLedger` | **Append-only.** Debit/credit lines per transaction |
  | `LedgerAccounts` | Chart of accounts, now including `CREDIT_RECEIVABLE`, `MERCHANT_PAYABLE`, `INTEREST_INCOME` |
  | `ReconciliationRuns` · `ReconciliationDiscrepancies` | Per-run match results |

  Transaction types: `EMI_MANUAL_PAY`, `EMI_AUTO_PAY`, `QR_UPI_PAYMENT`,
  `CREDIT_PURCHASE`, `CREDIT_BILL_PAYMENT`, `CREDIT_REFUND`, `CREDIT_LATE_FEE`,
  `FEE_DEBIT`, `REVERSAL_REFUND`, `PENNY_DROP`, and the retired `CARD_TO_BANK_TRANSFER`.

  **Immutability rule (PRD FR-010).** Financial rows are never hard-deleted or updated in
  place. Corrections are compensating entries (a refund is a new REFUND row, never an
  edit to the purchase).

  ### 8.7 Platform

  `Notifications` · `NotificationPreferences` · `NotificationTemplates` ·
  `DomainEvents` · `AuditLogs` · `AdminActivityLogs` · `AdminSettings` ·
  `FeatureFlags` · `SupportTickets` · `SupportMessages` · `TransactionErrors` ·
  `PlatformStatistics`

  **Removed:** `Transfers`, `TransferLimits`.

  ---

  ## 9. API surface

  flask-restx on `/v1`, Swagger at `/v1/doc/`.

  | Namespace | Endpoints |
  |---|---|
  | `/authentication` | `otp/send`, `otp/verify`, `register`, `mpin/set`, `mpin/verify`, `refresh`, `logout`, `sessions` (list / revoke) |
  | `/users` | `me` (get/patch), `me/security`, `me/login-history`, `me/export`, `me/erasure` |
  | `/kyc` | `status`, `submit` |
  | `/dashboard` | aggregate (FR-002), `activity` |
  | `/cards` | list, add, detail, update, unlink, `test-cards`, `networks/lookup/{bin}` |
  | `/bank-accounts` | list, add, detail, remove, `{id}/verify`, `{id}/primary`, `ifsc/{code}`, `lookup-account` |
  | **`/credit`** | `applications` (list / apply), `applications/{id}`, `applications/{id}/withdraw`, `eligibility`, `account`, `account/purpose` (get options / declare), `account/activate`, `account/block`, `account/unblock`, `purchases`, `transactions`, `transactions/{id}`, `statements`, `statements/current`, `statements/{id}`, `payments/methods`, `payments`, `payments/{id}/verify`, `payments/{id}/cancel` |
  | `/emi` | `providers`, `lookup`, obligations CRUD, `{id}/document` |
  | `/emi-payments` | `methods`, list, initiate, detail, `{id}/confirm`, `{id}/verify`, `{id}/cancel`, `{id}/receipt` |
  | `/mandates` | list, create, `preview`, detail, cancel, `{id}/activate`, `{id}/pause`, `{id}/resume` |
  | **`/qr-payments`** | `decode`, list, initiate, detail, `{id}/verify`, `{id}/cancel` |
  | `/transactions` | list (filtered, paginated), detail, `summary` |
  | `/notifications` | list, `{id}/read`, `read-all`, `preferences` |
  | `/support` | `tickets`, `tickets/{id}`, `tickets/{id}/reply`, `chat`, `escalate`, `transaction-error/{type}/{id}` |
  | `/webhooks` | `razorpay`, `cashfree/verification`, `cashfree/health` — **signature-verified, unauthenticated** |
  | `/admin` | dashboard, users (+ freeze/unfreeze), KYC queue + document + review, **credit applications + review, credit account detail/block/statement, credit refund**, reconciliation + self-audit, settings, feature flags, audit logs, admin activity, EMI verify, transaction errors (+ summary, resolve) |

  **Removed:** the whole `/transfers` namespace and its four admin endpoints; `/cards/{id}/pay-bill` (there is no rail for paying an external issuer — the card detail screen tells the user to pay their issuer directly).

  **Every state-changing money endpoint requires an `X-Idempotency-Key` header.**
  Amounts are parsed from raw text, never `type=float`, so `1e9` is rejected.

  ---

  ## 10. Critical flows

  ### 10.1 Credit line journey (end to end)

  ```
  Apply ──► KYC gate ──► Review ──► Approved (limit issued)
                                         │
                                         ▼
                         Purpose of credit ──► Activate ──► Spend
                                                              │
                   Credit restored ◄── Bill payment ◄── Statement
  ```

  | Step | Screen | What happens |
  |---|---|---|
  | 1. Apply | `/credit/apply` | Employment type, monthly income, existing EMI outflow (zero allowed), optional requested limit. A running **estimate** is shown, labelled as such and never sent. |
  | 2. KYC gate | `/credit/status/:id` | KYC tier NONE → `KYC_PENDING`. When an admin approves KYC, the application moves to `UNDER_REVIEW` immediately (not on next visit) and is re-assessed. |
  | 3. Review | `/credit/status/:id` | L2/L3 approves or rejects. Status polls for the decision and shows the real KYC sub-state and a timeline. |
  | 4. Issue | — | Approval issues a `CreditAccount` in `PENDING_PURPOSE`: RuPay BIN + random last 4, expiry +5 years. The middle digits are never composed. |
  | 5. Purpose | `/credit/purpose` | Accessible dropdown: Education, Medical, Shopping, Travel, Business, Bills, Emergency, Other. **Other requires a note; every other option refuses one.** Mandatory gate. |
  | 6. Activate | `/credit/activate` | `PENDING_ACTIVATION → ACTIVE`. Refused without a purpose. |
  | 7. Spend | `/credit/spend` | Details → review → receipt. One idempotency key per attempt, **kept across a retry** after a dropped connection. Declines are recorded as FAILED rows with a reason. |
  | 8. Statement | `/credit/statements` | Cut on the cycle day; due date = statement date + grace days. |
  | 9. Bill pay | `/credit/pay` | Amount → method → Razorpay Checkout → server verification. Resumes a payment already in flight instead of opening a second. |
  | 10. Restored | `/credit/transactions/:id` | Receipt with animated result, reference, available credit after. A processing payment is polled in the background. |

  The next screen is read from the server's `next_step` (`DECLARE_PURPOSE`,
  `ACTIVATE`, `UNBLOCK`, `NONE`), not inferred by the client.

  **State machines.**

  ```
  Application:  DRAFT → KYC_PENDING → UNDER_REVIEW ─┬→ APPROVED
                              │                     └→ REJECTED
                              └──────── WITHDRAWN (applicant, before decision)

  Account:      PENDING_PURPOSE → PENDING_ACTIVATION → ACTIVE ⇄ BLOCKED → CLOSED

  Transaction:  PENDING / PROCESSING → SUCCEEDED | FAILED | CANCELLED ;  SUCCEEDED → REVERSED (full refund)

  Statement:    UNPAID → PARTIALLY_PAID → PAID
                  └──────→ OVERDUE ;  older still-owing statements → CARRIED_FORWARD
  ```

  **Decision rules (`credit_engine.assess`).**

  | Rule | Value |
  |---|---|
  | KYC tier NONE | Not decided — `KYC_INCOMPLETE` |
  | Disposable income | monthly income − existing EMI outflow; ≤ 0 → `OBLIGATIONS_TOO_HIGH` |
  | Offer | 3 × disposable income |
  | Thin file (Student / Other) | capped at ₹20,000 |
  | Requested limit | honoured if lower; never raises the offer |
  | Tier cap | ₹50,000 (Minimum KYC) / ₹2,00,000 (Full KYC) |
  | Offer above ₹50,000 on Minimum KYC | `FULL_KYC_REQUIRED` — told to upgrade, not silently capped |
  | Floor | below ₹5,000 → `INCOME_BELOW_FLOOR` |
  | Rounding | down to the nearest ₹500 |
  | Admin override | may decline, or grant a different amount **within the tier cap**; never above |

  **Spending & billing settings** (admin-configurable, seeded defaults):

  | Parameter | Value |
  |---|---|
  | Daily spend limit | ₹1,00,000 |
  | Monthly spend limit | ₹2,50,000 |
  | Minimum payment | ₹1 |
  | Statement cycle day | 1st of the month |
  | Grace period | 18 days |
  | Minimum due | 5% of closing balance, plus any missed minimum from an overdue previous statement; whole balance if below ₹1 |
  | Late payment fee | ₹500, charged **once** per statement when the minimum due is not met by the due date |

  **Balance rules.**
  - Invariant after every movement: `available_credit + current_outstanding == credit_limit`.
  - Every balance change re-reads the account under `SELECT … FOR UPDATE` (with
    `populate_existing()`) inside one transaction.
  - **Credit balances are kept, as on a real card.** A refund after the bill is paid,
    or a payment that crosses a refund, leaves `current_outstanding` negative and
    available credit above the limit; the next spend uses it first. Never floored at
    zero. The API sends `credit_balance` as a positive figure.
  - A statement opens at the previous **full** closing balance. Older statements still
    owing become `CARRIED_FORWARD`, so one unpaid balance is never fee'd twice.
  - Fully refunded purchases (REVERSED) stay in the statement sweep alongside their
    refund row.
  - Refunds are admin-only (L2/L3, reason required), partial allowed, total never
    exceeds the purchase.

  **Bill payment — verified at the gateway (two halves).**

  ```
  POST /credit/payments ──► PROCESSING row + gateway order   (no balance touched)
         │
         ├─ /payments/{id}/verify   (browser)  ┐
         ├─ Razorpay webhook                   ├─► ask gateway ─► captured? ─► SUCCEEDED, credit restored (once)
         └─ credit_bill_payment_poll (2 min)   ┘                   └─ not paid ─► FAILED / CANCELLED
  /payments/{id}/cancel asks the gateway first (the payer may have paid and closed checkout).
  Unpaid after 30 min with no live attempt → closed as timed out.
  ```

  - One payment in flight per account (checked with a locking read).
  - Methods: UPI intent / collect (UPI, Google Pay, PhonePe, Paytm), net banking (bank
    logos; chosen bank is passed to Checkout), debit card. **Never a credit card.**
  - Amount may not exceed the outstanding, except that the ₹1 minimum may be paid
    against a smaller balance (the excess becomes credit).
  - **The simulator is refused when `ENV_NAME=production`**, whatever
    `USE_SANDBOX_ADAPTERS` says — the simulator reports every order paid, which would
    be free credit.
  - Dev builds show a simulated gateway sheet: approve, decline, close checkout, timeout.

  ### 10.2 Manual EMI payment lifecycle (PRD §11.1)

  ```
  INITIATED → PROCESSING → SUCCESSFUL → SETTLED
      │            │            │
  CANCELLED    PENDING      REVERSED → REFUNDED
                (poll 15min, 24h)
  ```

  Collected through Razorpay; confirmed by re-reading the payment from the gateway
  before the ledger moves, under a row lock (browser, webhook and poller can arrive
  together).

  **Hard rule (PRD §11.1, FR-008).** Credit cards — including the CashU credit line —
  are blocked as a payment instrument for loan EMIs. `CREDIT_CARD` is absent from the
  `PaymentMode` vocabulary, so there is no value a caller could pass to select it.

  ### 10.3 Auto-pay retry ladder (PRD §12.3)

  ```
  Attempt 1 — due date 04:00 IST
    ├─ success → post to ledger, mark paid, notify
    └─ insufficient funds → urgent alert
        Attempt 2 — T+1 day 11:30 IST (post-salary window)
          ├─ success → settle
          └─ fail
                Attempt 3 — T+2 days 18:00 IST (final)
                  └─ fail → disable auto-pay for cycle, flag OVERDUE, prompt manual
  ```

  **Mandate cap rule:** ≥110% of the monthly EMI. UPI AutoPay up to ₹15,000;
  e-NACH up to ₹10,00,000. Pre-debit notice 48h before.

  ### 10.4 Scan & Pay (UPI QR)

  ```
  Scan (/scan) → decode → confirm payee + amount → Razorpay UPI → verify at gateway → receipt
  ```

  - The QR is hostile input: only `upi://pay` deep links are parsed; `pa` is required,
    every kept field is validated, unknown fields are dropped, raw text is never echoed.
    `sign`/`orgid` are ignored rather than pretending to verify them.
  - If the QR has no amount (a reused shop sticker), the payer enters it.
  - Money leaves the user's **bank** via UPI — not the credit line. KYC (Minimum) required.
  - Same confirmation rules as EMI: gateway re-read, row lock, ledger posted once.

  ### 10.5 Failed payments & support

  Every failed payment (EMI, QR, credit bill, declined purchase) is recorded in
  `TransactionErrors` with a catalogued cause. The support assistant is **scripted, not
  generative**: each reply is assembled from the recorded failure, so it never invents
  a reason. The user can escalate to a ticket; L1–L3 see the error centre and resolve.

  ### 10.6 Retired — credit-to-bank transfer

  The FR-006 state machine (INITIATED → … → SUCCEEDED / REVERSED_TO_CARD), its fee
  (1.95% + 18% GST), limits, payout circuit breaker, risk engine and screens were
  removed in `5b64317`. Historical rows remain in the ledger.

  ---

  ## 11. Notification matrix (PRD §14)

  Events are written to the `domain_events` outbox by `audit.emit()` and dispatched by
  `notify.dispatch()` (channel routing lives in `notify.py`).

  | Trigger | Priority | Status |
  |---|---|---|
  | New card linked | High | ✅ Sent |
  | Bank account verified | Medium | ✅ Sent |
  | KYC approved / rejected | High | ✅ Sent |
  | Suspicious login / new device | Critical | ✅ Sent |
  | **Auto-pay pre-debit T-2** | **Critical — RBI e-Mandate** | ✅ Sent |
  | Auto-pay debit succeeded / failed | High / Critical | ✅ Sent |
  | EMI due T-7 / T-1 | Low / High | ⚠ **Templates defined, nothing sends them** — the 09:00 job only flags overdue EMIs |
  | Credit application decided | High | ⛔ **Not built** |
  | Statement generated / payment due | High | ⛔ **Not built** |
  | Credit purchase / bill payment / late fee | High | ⛔ **Not built** |
  | ~~Transfer succeeded / failed~~ | — | Retired (templates `CASHU_TXF_*` still seeded) |

  Push (FCM/APNS) is P1. **Transactional alerts cannot be disabled by the user.**

  > **Gap.** `credit_engine` writes audit rows but emits no notification events, and EMI
  > due reminders are never scheduled. Both are the next notification work items.

  ---

  ## 12. RBAC (PRD §15)

  | Capability | User | L1 Support | L2 Risk/Recon | L3 Super Admin |
  |---|:--:|:--:|:--:|:--:|
  | Own dashboard, cards, EMIs, credit line | ✅ | ❌ | ❌ | ❌ |
  | Apply, spend, pay bill, block/unblock own card | ✅ | ❌ | ❌ | ❌ |
  | View masked users, credit applications, credit accounts, transaction errors | ❌ | ✅ | ✅ | ✅ |
  | View raw PII / KYC documents | ❌ | ❌ | ✅ *(audited)* | ✅ *(audited)* |
  | Review KYC, freeze/unfreeze users | ❌ | ❌ | ✅ | ✅ |
  | **Approve / reject credit applications** | ❌ | ❌ | ✅ | ✅ |
  | **Block a credit account, refund a purchase** | ❌ | ❌ | ✅ | ✅ |
  | **Cut an out-of-cycle statement** | ❌ | ❌ | ❌ | ✅ |
  | Reconciliation, self-audit, audit logs | ❌ | ❌ | ✅ | ✅ |
  | Settings & feature flags | ❌ | ❌ | ❌ | ✅ |
  | Direct production DB access | ❌ | ❌ | ❌ | **❌ (zero-DB)** |

  An admin can approve a credit line but **cannot declare a purpose or activate on the
  applicant's behalf**. Maker-checker threshold remains ₹25,000.

  Admin UI modules: dashboard · users · KYC queue + document viewer · reconciliation ·
  settings. *(Credit application queue is API-only today.)*

  ---

  ## 13. Security & compliance

  ### 13.1 Non-negotiable rules

  1. **Zero raw card storage.** No PAN, CVV, or PIN ever enters CashU. External cards
     are stored as BIN + last 4. The issued CashU card is generated as BIN + last 4
     only — the middle digits are never composed. `static_audit` asserts no such column
     exists, against both models and the live schema.
  2. **Money is credited only on a gateway-verified status.** A signature proves a
     message wasn't forged, not that money moved — every caller re-reads the payment
     from the gateway before the ledger or a credit balance moves.
  3. **The simulator is refused in production** for credit bill payments.
  4. **Bank accounts must be penny-drop verified** as belonging to the user (PMLA).
  5. **Credit cannot pay loan EMIs.** Structurally enforced.
  6. **Idempotency key required** on every money-moving request, `UNIQUE`-enforced.
  7. **Financial rows are append-only.** Corrections are compensating entries.
  8. **Clients never supply a limit or a balance.** Only `credit_engine` computes them.
  9. **PII encrypted at rest** — AES-256-GCM field-level.
  10. **Every admin mutation writes an audit row** with actor, IP, timestamp, before/after.
  11. **Test cards and test spends are dev-only** — refused in production and outside
      sandbox adapters; test rows carry `is_test`.

  ### 13.2 Rate limits (PRD §17.1)

  | Endpoint class | Limit |
  |---|---|
  | Public auth | 5 req/min per IP |
  | OTP resend | 3 per 15-min window per IP/device; OTP expires in 180s |
  | Failed auth | 3 attempts → 30-min lockout |
  | Payment velocity | >3 payments in 1 hour → 30-min throttle + security alert (ERR-011) |
  | Credit spend | ₹1,00,000/day, ₹2,50,000/month (summed from rows under the account lock) |

  ### 13.3 Compliance checklist (PRD §18)

  | Area | Requirement | v1 status |
  |---|---|---|
  | Credit Card Master Direction | Card issuance only by/with a licensed issuer; no cash cycling | Transfers removed ✅; **issuing partner ⛔ unsigned** |
  | DPDPA 2023 | Granular consent, right to erasure, data localization | Export + erasure in v1 |
  | PCI DSS v4.0 | SAQ-A profile | Architecturally satisfied — no PAN anywhere |
  | KYC / AML | Min KYC to use; Full KYC for credit limits above ₹50,000 | Tiering in v1; manual review queue |
  | NPCI e-Mandate | AFA at registration, pre-debit notice, pause/cancel | In v1 (sandbox rail) |
  | NPCI UPI | Scan & Pay via a licensed PA | Razorpay; **UPI not yet enabled on the merchant account** |
  | BBPS | Via licensed BBPOU or Agent Institution | Adapter built; **vendor unsigned** |
  | PA/PG licensing | Partner with licensed PA; hold no client funds | Razorpay + Cashfree; no funds held ✅ |

  ---

  ## 14. Vendor adapter seams

  Selected in `adapters.py` by `USE_SANDBOX_ADAPTERS` **and** whether credentials are
  present — a half-configured environment degrades to the simulator instead of failing
  mid-payment.

  | Seam | Sandbox behaviour | Live |
  |---|---|---|
  | Collection (credit bill, EMI, Scan & Pay) | Simulated order; injectable DECLINE / ABANDON / TIMEOUT | **Razorpay** Checkout + webhook |
  | Penny drop / IFSC | Configurable CBS name for match/mismatch | **Cashfree** Verification Suite |
  | EMI biller | Bajaj Finance sandbox | BBPS BOU / Bajaj B2B — unsigned |
  | Mandate | Simulated UMN, scheduled debit, bounce injection | Razorpay AutoPay / Cashfree / NPCI — unsigned |
  | KYC | Manual admin review queue | Bureau.id, Karza, Signzy, IDfy — unsigned |
  | Card issuance | Internal (BIN + last 4) | **Issuing partner — unsigned** |
  | SMS / Email | Console sink / Flask-Mail | Gupshup, Exotel, Karix |
  | Push | No-op (P1) | FCM, OneSignal |

  **Design constraint:** swapping a sandbox for a live vendor touches one adapter file
  plus configuration. **Failure injection is a v1 requirement.**

  ---

  ## 15. Build order & status

  | Phase | Deliverable | Status |
  |---|---|---|
  | 0 | Skeleton, config, logger, health, Docker, seeders | ✅ |
  | 1 | Identity: OTP, MPIN, JWT, device binding, sessions, rate limits | ✅ |
  | 2 | Profile + KYC tiering + admin review queue | ✅ |
  | 3 | Ledger engine + master transactions + self-audit | ✅ |
  | 4 | External card tracking | ✅ |
  | 5 | Bank accounts + penny drop + IFSC | ✅ |
  | 6 | Dashboard aggregation (FR-002) | ✅ |
  | 7 | ~~Transfer engine~~ → **Credit line backend** (`0f20029`, `28c6286`, `a1d426c`) | ✅ |
  | 7b | **Credit line UI** — 9 screens, nav history (`ef02c50`, `f182906`) | ✅ |
  | 8 | EMI registry + Bajaj sandbox + manual payment (Razorpay) | ✅ |
  | 8b | Scan & Pay (UPI QR) | ✅ |
  | 9 | Mandate engine + pre-debit + retry ladder | ✅ (sandbox) |
  | 10 | Notification engine | ⚠ credit-line events missing |
  | 11 | Transaction history, receipts, reconciliation | ✅ |
  | 12 | Admin console + RBAC + audit | ✅ (credit application queue UI pending) |
  | 13 | Frontend polish — motion, empty/error states, receipt moment | ✅ |
  | 14 | Test suites (§17) | ✅ — 3 suites carry a known BLOCKED check |
  | 15 | Production hardening — once vendors are signed | ⛔ Blocked |

  ---

  ## 16. Open decisions

  | # | Decision | Impact | Status |
  |---|---|---|---|
  | 1 | ~~Transfer merchant model~~ → **Credit line issuing partner** — bank co-brand or NBFC co-lending? Who owns the book? | **Legal — the whole credit pillar** | ⛔ Open |
  | 2 | BBPS integration — direct AI via BBPOU, or Bajaj B2B? | Regulatory / Ops | ⛔ Open |
  | 3 | ~~Token Requestor partner~~ | — | ✅ Closed — no tokenisation needed; only BIN + last 4 stored |
  | 4 | KYC tiering — is Min KYC acceptable for limits up to ₹50,000? | Compliance | ⛔ Open (implemented as yes) |
  | 5 | ~~Fee absorption on transfers~~ | — | ✅ Closed — transfers removed |
  | 6 | Cross-border / NRI cards | Legal | ✅ Closed — domestic INR only |
  | 7 | ~~Chargeback liability post-IMPS payout~~ | — | ✅ Closed — transfers removed |
  | 8 | MySQL vs PostgreSQL (⚑ D1) | Revisit only if the self-audit shows drift | MySQL |
  | 9 | Redis in v1 (⚑ D2) | Skip; UNIQUE idempotency is stronger | No Redis |
  | 10 | UUID vs integer PKs (⚑ D6) | UUID on financial entities | UUID |
  | 11 | **Interest on revolving balances** | Revenue / disclosure | ⛔ Open — v1 charges only a late fee |
  | 12 | **Enable UPI on the Razorpay merchant account** | Scan & Pay, UPI bill pay live | ⛔ Open |

  ---

  ## 17. Acceptance criteria & tests

  ### 17.1 Acceptance criteria

  - **AC-001** External card linking — only BIN + last 4 stored, **zero raw PAN/CVV in
    the database**, masked card shown.
  - ~~**AC-002** Transfer with fee disclosure~~ — retired with FR-006.
  - **AC-003** Pre-debit notification — T-48h SMS + Email with UMN, amount, date,
    biller; audit row recorded.
  - **AC-004** Idempotency — a duplicate key returns the original transaction, **no
    second charge** (EMI, QR, credit purchase, bill payment).
  - **AC-005** Credit line journey — apply → KYC → approve → purpose → activate →
    spend → statement → pay → credit restored, with the invariant holding after
    every movement.
  - **AC-006** Bill payment restores credit **only after the gateway reports capture**;
    concurrent verify / webhook / poller restore it exactly once.
  - **AC-007** Concurrent purchases on one account never exceed available credit and
    each records a distinct running balance.
  - **AC-008** Statements across cycles: no double-counted payments, refunds kept as
    credit, carried-forward statements not fee'd twice.

  ### 17.2 Suites (`backend/tests/run_all.py`)

  `run_all.py` clears throttle counters between suites (running them back to back
  otherwise trips the OTP limiter and fails misleadingly) and knows which suites end on
  a deliberate BLOCKED check.

  | Suite | Covers |
  |---|---|
  | `static_audit` | JWT coverage, no PAN/CVV columns (model + live schema) |
  | `validation_audit` | Input validation, raw-text amounts |
  | `credit_lifecycle` | Full credit journey + API field contract |
  | `credit_concurrency` | Racing purchases, racing bill-payment opens, verify storms |
  | `credit_statement_cycles` | Multi-cycle statements, refunds as credit, carry-forward |
  | `upi_payment_flow`, `upi_webhook` | Scan & Pay + Razorpay webhook (gateway-signature checks skipped while UPI is off) |
  | `smoke_flow`, `test_card_flow`, `error_support_flow` | ⚠ One known BLOCKED check each — their money leg was the transfer; to be retargeted onto credit purchases |
  | `frontend/scripts/ui-audit.mjs` | Route and navigation-target resolution |
  | Browser e2e | puppeteer-core + installed Chrome against Vite :3000, at 320 / 375 / 768 / 1280px — 71 checks, no horizontal scroll, no console errors |

  ---

  ## 18. Local environment

  ```bash
  cp backend/.env.example backend/.env     # fill in secrets first
  docker compose up --build
  ```

  | Service | URL |
  |---|---|
  | Frontend | http://localhost:3000 |
  | API | http://localhost:5050/v1 |
  | Swagger | http://localhost:5050/v1/doc/ |
  | MySQL (compose) | `localhost:3307` — root / Mahesh2605 / `cashu_db` |

  Compose binds MySQL to host port **3307** because the native MySQL install used for
  local (non-Docker) dev already holds 3306. `USE_SANDBOX_ADAPTERS=True` by default;
  set `ENV_NAME=production` in any real deployment so the simulator is refused for
  bill payments.

  ---

  *End of CashU Version 1 Specification, revision 2. Derived from PRD v1.0.0-PROD-SPEC.*
