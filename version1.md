# CashU — Version 1 Specification

> **Derived from:** Project Requirement Document (PRD) v1.0.0-PROD-SPEC —
> *"CredFlow / Unified Credit & EMI Management Platform"*, working title `cred_v1`.
> **This document:** v1 build specification · **Date:** 2026-09-09 · **Owner:** Mahesh
>
> The PRD is the source of truth for *what* CashU is. This document is the source of
> truth for *how v1 gets built* on the chosen stack — it takes the PRD's P0 slice and
> maps it onto a Flask/MySQL monolith following the stockverse house structure.
>
> Where this document departs from the PRD, the departure is marked **⚑ DEVIATION**
> with the reason. Nothing is silently dropped.

---

## 1. Product identity

| Attribute | Value |
|---|---|
| Product name | **CashU** |
| PRD codename | CredFlow / Unified Credit & EMI Hub (`cred_v1`) |
| Market | India (INR only, domestic cards and banks) |
| Release | Version 1.0 — MVP, production-intent |
| Regulatory posture | RBI CoFT · DPDPA 2023 · PCI DSS v4.0 SAQ-A · PMLA · NPCI e-Mandate |

**One line:** CashU unifies a user's credit cards and NBFC loan EMIs under a single
dashboard, lets them service those obligations without visiting six banking portals,
and provides a regulated credit-facility-to-bank liquidity transfer.

**What CashU is not.** Not a rewards or cashback app. Not a wallet — CashU holds no
customer funds. Not a lender. Not a card issuer. It is a technology layer on top of
licensed partners.

---

## 2. The three pillars of v1

Everything in v1 serves one of three jobs. If a proposed feature serves none, it is
out of scope.

| Pillar | User job | Anchor requirements |
|---|---|---|
| **1. See** | "Show me everything I owe, in one place, without anxiety." | FR-002 dashboard, FR-003 card linking, FR-004 card detail, FR-007 EMI registry |
| **2. Service** | "Let me pay what's due without hunting for a portal." | FR-008 manual EMI pay, FR-009 auto-pay mandates |
| **3. Access** | "Let me turn credit headroom into bank liquidity, transparently." | FR-005 penny-drop, FR-006 credit-to-bank transfer |

Underneath all three: FR-001 identity, FR-010 ledger, FR-011 notifications,
FR-012 profile/KYC/security.

---

## 3. Brand & UI direction

The PRD specifies function, not visual identity. This section is the design contract.

### 3.1 Palette

| Token | Value | Role |
|---|---|---|
| `--cashu-mint` | `#00F5B8` | **Primary accent** — CTAs, active states, positive deltas, focus rings |
| `--cashu-canvas` | `#FFFFFF` | **Primary background** |
| `--cashu-ink` | `#0A0F0D` | Primary text; dark surfaces (card tiles, the transfer sheet) |
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
The transfer success screen is the single "moment" — everything else is quiet.

**Type.** One geometric sans. All monetary values in tabular-lining numerals so digits
don't jitter during count-up or live refresh.

**Copy.** Never scold. "₹4,250 due in 3 days" — not "You're late." Failure messages
state the cause and the next action, per the PRD §20 user-facing message column.

### 3.3 Logo

**Concept — "The Coin Cut."** A `U` drawn as the lower arc of a coin, its negative
space cutting an upward notch: reads simultaneously as currency and as headroom
recovered. Mint on white, ink on mint, single-colour safe, legible at 16px.

Alternates: monogram `C` whose counter forms a `U`; a rupee stroke integrated into the
`U` stem; wordmark with one mint accent letter.

Deliverables: app icon (1024/512/192/32), horizontal lockup, monochrome, favicon,
splash mark.

---

## 4. Target users

Straight from PRD §4 — the build serves these four, in this priority order.

| Persona | Who | What v1 gives them |
|---|---|---|
| **Multi-Card Maximizer** *(primary)* | 26–42, salaried, 3–6 cards, ₹8L–₹30L p.a. | Aggregate limit, utilization warning, unified due calendar |
| **Consumer EMI Repayer** *(primary)* | 22–48, consumer-durable / two-wheeler loans via Bajaj, HDB, IDFC | Biller discovery, one-tap UPI payment, auto-pay scheduling |
| **Emergency Liquidity Seeker** *(secondary)* | Freelancer / trader with mid-month cash-flow gaps | Compliant credit-to-bank transfer, upfront fee breakdown, instant IMPS |
| **Ops & Compliance Staff** *(internal)* | Risk analysts, support, settlement accountants | RBAC console, immutable audit trail, recon dashboard |

---

## 5. Scope boundary

### 5.1 In — v1.0 (PRD P0, all mandatory)

| # | Capability | FR |
|---|---|---|
| 1 | Mobile + OTP authentication, 6-digit MPIN, device binding | FR-001 |
| 2 | Home dashboard — aggregate limit, utilization, nearest due | FR-002 |
| 3 | Credit card linking via CoFT tokenization, masked display | FR-003 |
| 4 | Card detail, billing cycle config, unlink + token revocation | FR-004 |
| 5 | Bank account linking with ₹1 penny-drop name verification | FR-005 |
| 6 | Credit-facility → bank transfer with fee disclosure | FR-006 |
| 7 | EMI obligation registry (Bajaj Finance anchor adapter) | FR-007 |
| 8 | Manual EMI payment via UPI / netbanking | FR-008 |
| 9 | Recurring auto-pay via NPCI e-Mandate / UPI AutoPay | FR-009 |
| 10 | Double-entry immutable ledger + transaction history | FR-010 |
| 11 | Notification & alert engine (SMS/Email/Push/In-App) | FR-011 |
| 12 | Profile, KYC tiering, security settings | FR-012 |
| 13 | RBAC admin & operations console | §15, §16 |

### 5.2 Deferred — explicitly not v1

| Deferred to | Items |
|---|---|
| **Phase 1.1 (P1)** | Push via FCM/APNS, additional EMI providers (HDB, IDFC), smart auto-pay retries, biometric unlock |
| **Phase 2.0 (P2)** | Account Aggregator statement sync, credit score tracking (CIBIL/Experian) |
| **Phase 3.0 (P3)** | Card reward-points optimization, split-card payments |
| **Never (non-goals)** | Direct card issuance, P2P money laundering / cash cycling, crypto, raw PAN/CVV/PIN storage, unlicensed P2P lending, physical POS |

> **Note.** Rewards, coins, cashback, and a user wallet are **not** part of CashU.
> Reward-points optimization is P3. CashU never holds customer funds.

---

## 6. Stack & the PRD deviations

### 6.1 Chosen stack

| Layer | Choice |
|---|---|
| Frontend | React.js + Tailwind CSS + Vite |
| Backend | Python 3.12 · Flask · flask-restx · Flask-SQLAlchemy |
| Database | **MySQL 8.4** (InnoDB, utf8mb4) |
| Auth | flask-jwt-extended |
| Scheduler | APScheduler |
| Container | Docker + docker compose |

### 6.2 ⚑ DEVIATIONS from PRD infrastructure

The PRD specifies enterprise infrastructure appropriate to a funded, licensed
operation. v1 is built as a modular monolith on the chosen stack. Each deviation
below is deliberate, with the mitigation named.

| # | PRD specifies | v1 does | Consequence & mitigation |
|---|---|---|---|
| **D1** | PostgreSQL | **MySQL 8.4** | Per your stack decision. Ledger integrity preserved via InnoDB + explicit `REPEATABLE READ` transactions with `SELECT … FOR UPDATE` on balance-affecting rows. **Every ledger write must be inside an explicit transaction** — this is not optional and is the single highest-risk area of the port. |
| **D2** | Redis (OTP hash 180s TTL, sliding-window rate limits, 24h idempotency keys) | **MySQL tables + APScheduler sweeps** | `otp_verifications` carries `expires_at`; rate limits become counter rows on a time bucket; **idempotency is enforced by a `UNIQUE` index on `master_transactions.idempotency_key`** — a duplicate insert raises `IntegrityError`, which the handler catches and returns the original transaction. This is stricter than Redis, not weaker. A janitor job purges expired rows. Redis remains a drop-in optimisation later. |
| **D3** | Microservices on Kubernetes/EKS with HPA | **Modular Flask monolith** | Each PRD "service" (Auth, Card & Token, Transfer & Payout, EMI & BBPS, Auto-Pay, Ledger, Notification, Audit & Risk) becomes an *engine module* in `portal/helpers/` with a defined interface. Extraction to a service later is a deployment change, not a rewrite — provided no engine reaches into another's tables directly. |
| **D4** | Kafka / RabbitMQ event bus with outbox | **In-process domain events + APScheduler workers** | A `domain_events` table plays the outbox role; the scheduler drains it. Preserves at-least-once semantics and the audit trail; loses cross-service fan-out CashU doesn't yet need. |
| **D5** | React Native (iOS/Android) + Next.js | **React + Vite responsive web** | v1 is responsive web, mobile-first. Native shell is post-v1. |
| **D6** | Integer autoincrement (stockverse house style) | **UUIDv4 primary keys** on financial entities | Per PRD §13/§23. Sequential IDs on cards, transfers, and transactions are enumerable and leak volume; a fintech should not expose them. Stored `CHAR(36)`. Lookup/reference tables (`roles`, `providers`) keep integer PKs. |
| **D7** | Multi-AZ, 99.95% SLA, PITR, WORM audit storage | Single-node dev/staging | Production hardening is a deployment concern, deferred until a licensed partner is signed. Audit rows are append-only *by application rule* now; WORM storage comes with production. |

### 6.3 What these deviations cost

Honest accounting: **D1 and D2 are the ones that can bite.** The ledger's correctness
now depends on discipline in application code rather than the database's strongest
isolation guarantees. Mitigations: every money path goes through a single
`ledger_engine.post()` function, no exceptions; a nightly self-audit job asserts that
debits equal credits per transaction and that derived balances match ledger sums,
raising a critical alert on drift. This job is a v1 deliverable, not a nice-to-have.

---

## 7. Architecture

### 7.1 Repository layout

```
CashU/
├── backend/                          Flask API — mirrors stockverse exactly
│   ├── app.py                        entry point; create_all + seeders; port 5050
│   ├── config/
│   │   ├── config.py                 Development / Testing / Production classes
│   │   └── dev.ini · uat.ini · prod.ini
│   ├── portal/
│   │   ├── __init__.py               InitApp class, APP singleton, db = SQLAlchemy()
│   │   ├── extensions.py             shared db / migrate instances
│   │   ├── logger.py                 rotating file + stream handler
│   │   ├── scheduler.py              APScheduler registrations (see §7.3)
│   │   ├── seeds.py
│   │   ├── api/__init__.py           flask-restx Api on the /v1 blueprint
│   │   ├── helpers/                  the engines — see §7.2
│   │   ├── models/                   one model per file
│   │   ├── routes/                   one package per domain namespace
│   │   ├── seeders/                  idempotent, dependency-ordered
│   │   └── uploads/                  KYC documents, loan sanction letters
│   ├── migrations/                   Flask-Migrate
│   ├── tests/
│   ├── logs/
│   ├── requirements.txt
│   ├── Dockerfile · docker-entrypoint.sh · .dockerignore
│   └── .env · .env.example
│
├── frontend/                         React + Vite + Tailwind
│   ├── src/
│   │   ├── app/                      App.jsx, routes.jsx
│   │   ├── components/               shared UI primitives
│   │   ├── pages/
│   │   │   ├── auth/                 onboarding, OTP, MPIN
│   │   │   ├── user/                 dashboard, cards, transfer, emi, transactions, profile
│   │   │   └── admin/                console modules
│   │   ├── context/                  AuthContext, DashboardContext
│   │   ├── hooks/  api/  utils/  styles/
│   ├── Dockerfile · nginx.conf
│
├── docker-compose.yml                MySQL 8.4 + backend + frontend
└── version1.md                       this document
```

### 7.2 Engines — PRD services mapped to `portal/helpers/`

| PRD service (§22) | v1 module | Responsibility |
|---|---|---|
| Auth & User Service | `jwt.py`, `otp.py`, `device_binding.py` | Token issue/rotate, OTP lifecycle, device UUID binding |
| Card & Token Service | `token_requestor.py` | CoFT adapter; masked metadata; token revoke |
| Transfer & Payout Engine | `transfer_engine.py`, `fee_calculator.py`, `idempotency.py` | FR-006 state machine, fee + GST maths, duplicate defence |
| EMI & BBPS Service | `emi_provider_adapter.py`, `bbps_adapter.py` | Biller lookup, EMI payment rail |
| Auto-Pay Mandate Engine | `mandate_engine.py` | e-Mandate registration, pre-debit scheduling, retry ladder |
| Double-Entry Ledger | `ledger_engine.py` | **The only writer of ledger rows.** Post, reverse, reconcile |
| Notification Service | `notify.py`, `sms.py`, `email.py`, `templates/` | Channel routing per §14 matrix |
| Audit & Risk Engine | `risk_engine.py`, `audit.py` | Velocity limits, BIN blocklist, immutable audit writes |
| — | `encryption.py` | AES-256-GCM field encryption for PII, bank numbers, tokens |
| — | `validators.py` | IFSC, PAN, mobile, LAN, amount, pagination |

**Hard rule.** `ledger_engine.post()` is the sole entry point for any monetary state
change. No route, no other engine, writes to `master_transactions` or
`double_entry_ledger` directly.

### 7.3 Scheduled jobs (`scheduler.py`)

| Job | Cadence | Purpose | PRD ref |
|---|---|---|---|
| `mandate_predebit_notice` | daily 10:00 IST | T-48h pre-debit SMS+Email — **regulatory, non-negotiable** | §12.2 |
| `mandate_execute` | daily 04:00 IST | Trigger due mandate debits | §12.3 |
| `mandate_retry` | daily 11:30 & 18:00 IST | Retry ladder attempts 2 and 3 | §12.3 |
| `emi_due_reminder` | daily 09:00 IST | T-7 and T-1 reminders | §14 |
| `payment_status_poll` | every 15 min | Poll PENDING payments up to 24h | FR-008 |
| `transfer_recon` | every 6 h | Three-way reconciliation (T+0, T+1) | §9.4 |
| `ledger_self_audit` | nightly | Assert debits == credits; flag drift | ⚑ D1 mitigation |
| `domain_event_drain` | every 1 min | Outbox → notification dispatch | ⚑ D4 |
| `token_expiry_sweep` | daily | Flag cards past expiry, notify | ERR-009 |
| `otp_janitor` | hourly | Purge expired OTP + rate-limit rows | ⚑ D2 |

---

## 8. Data model

Follows PRD §23 ERD and §13.1 transaction schema, expressed in stockverse house style:
plural class names, sibling status-constant classes, `created_on` / `updated_on`,
and `save()` / `update()` / `delete()` instance helpers.

Money is `Numeric(12,2)` per PRD §13.1. Timestamps are UTC.

### 8.1 Identity & access

| Model | Notes |
|---|---|
| `Roles` | `RoleTypes`: `NORMAL_USER`, `L1_SUPPORT`, `L2_RISK_RECON`, `L3_SUPER_ADMIN` |
| `Users` | phone (unique, indexed), full_name, email, `kyc_tier`, `mpin_hash`, is_active |
| `UserProfiles` | PAN (encrypted), DOB, address; `KYCTier`: `NONE`/`MINIMUM`/`FULL` |
| `UserSessions` | device UUID binding, refresh-token fingerprint, revocation |
| `OTPVerifications` | hashed OTP, `expires_at`, attempt count, `OTPPurpose` |
| `LoginHistory` | IP, user agent, device, `LoginStatus` |
| `UserSecuritySettings` | biometric toggle, session kill switch |
| `KYCVerifications` | PAN/Aadhaar docs, `KYCStatus`, reviewer, rejection reason |
| `DeviceBindings` | device UUID, carrier signature, trusted flag |

### 8.2 Cards & banking

| Model | Notes |
|---|---|
| `Cards` | `token_reference_id`, `masked_pan`, `issuer_bank`, `network`, `card_limit`, `due_day`, `CardStatus`. **Never a PAN, CVV, or PIN column — enforced at review.** |
| `CardNetworks` | Visa / Mastercard / RuPay / Amex reference + BIN routing |
| `BankAccounts` | `account_number_enc`, `ifsc_code`, `bank_name`, `verified_cbs_name`, `PennyDropStatus`, `is_primary` |
| `PennyDropVerifications` | ₹1 IMPS ref, CBS name returned, similarity score, decision |

### 8.3 Transfers

| Model | Notes |
|---|---|
| `Transfers` | card_id, bank_account_id, gross/fee/tax/net, `idempotency_key` **(UNIQUE)**, `TransferStatus` (§9.3 state machine), `bank_rrn_utr` |
| `TransferLimits` | per-user rolling daily/monthly counters |

### 8.4 EMI

| Model | Notes |
|---|---|
| `EMIProviders` | Bajaj Finance, HDB, IDFC…; adapter key; BBPS biller id |
| `EMIObligations` | `loan_account_no` (masked in UI), `loan_type`, `emi_amount`, `due_day_of_month`, `total_tenure`, `tenure_remaining`, `outstanding_bal`, `auto_pay_status`, `payment_status` — matches PRD §10.2 exactly |
| `EMIPayments` | amount, `payment_mode`, `bbps_rrn`, `EMIPaymentStatus` (§11.1 lifecycle) |
| `AutoPayMandates` | `mandate_umn`, `max_amount`, `frequency`, `next_debit_date`, `MandateStatus` |
| `MandateDebitAttempts` | attempt no., scheduled_at, result, bounce code — drives the §12.3 retry ladder |

### 8.5 Ledger & money (the core)

| Model | Notes |
|---|---|
| `MasterTransactions` | PRD §13.1 verbatim: `transaction_type`, gross/net/fee/tax, source/dest type + masked ref, `gateway_provider`, `gateway_ref_no`, `bank_rrn_utr`, `idempotency_key` (UNIQUE), `status`, `failure_code`, `failure_reason`, `recon_status` |
| `DoubleEntryLedger` | `transaction_id` FK, `account_code` (Asset/Liability), `debit_amount`, `credit_amount`, `currency`, `entry_timestamp`. **Append-only.** |
| `LedgerAccounts` | chart of accounts — the `account_code` vocabulary |
| `ReconciliationRuns` | per-run three-way match results, discrepancies |

**Immutability rule (PRD FR-010).** Financial rows are never hard-deleted or updated in
place. Corrections are compensating journal entries. Enforced by application rule and
verified by the nightly self-audit; there is no `delete()` helper on these models.

### 8.6 Platform

`Notifications` · `NotificationPreferences` · `NotificationTemplates` ·
`DomainEvents` (outbox) · `AuditLogs` · `AdminActivityLogs` · `AdminSettings` ·
`FeatureFlags` · `RateLimitCounters` · `SupportMessages` · `PlatformStatistics`

---

## 9. API surface

flask-restx on `/v1`, Swagger at `/v1/doc/`. One route package per namespace, each with
`__init__.py` declaring `ns = api.namespace(...)` then `from .routes import *`.

| Namespace | Endpoints |
|---|---|
| `/authentication` | `otp/send`, `otp/verify`, `mpin/set`, `mpin/verify`, `refresh`, `logout` |
| `/users` | profile get/update, admin user management |
| `/kyc` | submit, status, admin approve/reject |
| `/dashboard` | aggregate telemetry (FR-002 payload) |
| `/cards` | list, initiate-link, link-callback, detail, update-cycle, unlink |
| `/bank-accounts` | list, add, penny-drop status, set-primary, remove |
| `/transfers` | quote (fee breakdown), initiate, confirm, status, history |
| `/emi` | providers, obligations CRUD, lookup-biller, schedule |
| `/emi-payments` | initiate, status, receipt |
| `/mandates` | create, status, pause, resume, cancel |
| `/transactions` | list (filtered, paginated), detail, receipt PDF |
| `/notifications` | list, mark-read, preferences |
| `/webhooks` | gateway, BBPS, mandate, payout — **signature-verified, unauthenticated** |
| `/admin` | users, transactions, reversals, recon, risk, audit, settings, flags |
| `/support` | threads, messages |
| `/health` | liveness — used by the Docker HEALTHCHECK |

**Every state-changing money endpoint requires an `X-Idempotency-Key` header.**

---

## 10. Critical flows

### 10.1 Credit-to-bank transfer — state machine (PRD §9.3)

```
INITIATED → RISK_CHECKED ─┬─(rejected)→ RISK_FAILED
                          └─(cleared)→ AUTH_PENDING → INBOUND_CHARGED
                                                        ├─(payout ok)→ SUCCEEDED
                                                        └─(payout fails)→ PAYOUT_PROCESSING
                                                              ├─(retry ok)→ SUCCEEDED
                                                              └─(3 retries fail)→ REVERSAL_INIT → REVERSED_TO_CARD
```

**Limits & fees (PRD §9.2)** — all admin-configurable, seeded to these defaults:

| Parameter | Value |
|---|---|
| Minimum transfer | ₹1,000 |
| Maximum single | ₹50,000 (Standard KYC) / ₹1,00,000 (Enhanced KYC) |
| Daily cumulative | ₹1,00,000 rolling 24h |
| Monthly cumulative | ₹2,50,000 calendar month |
| Convenience fee | 1.95% of principal |
| GST | 18% on the fee only |
| Disclosure | Non-skippable breakdown before 3DS auth |

**Failure circuit breaker (PRD §9.4).** Card charged but IMPS payout fails → 3 retries
with exponential backoff (2min, 5min, 15min) → `REVERSAL_INIT` → automatic inbound
refund to source card → high-priority user alert explaining exactly what happened.

### 10.2 Manual EMI payment lifecycle (PRD §11.1)

```
INITIATED → PROCESSING → SUCCESSFUL → SETTLED
    │            │            │
 CANCELLED    PENDING      REVERSED → REFUNDED
              (poll 15min, 24h)
```

**Hard rule (PRD §11.1, FR-008).** Credit cards are blocked as a payment instrument
for loan EMIs — RBI prohibits servicing debt with a revolving credit line. Permitted:
UPI, netbanking, debit card. Enforced server-side, not just hidden in the UI.

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

**Mandate cap rule:** must be ≥110% of the monthly EMI to absorb interest adjustments
while still bounding arbitrary debits.

---

## 11. Notification matrix (PRD §14)

| Trigger | Channels | Priority | Regulatory |
|---|---|---|---|
| New card linked | In-App, Push, SMS | High | RBI Cyber Security Mandate |
| Transfer initiated | In-App, Push | Medium | UX |
| Transfer succeeded | In-App, Push, SMS, Email | High | Audit / consumer protection |
| Transfer failed / reversal | In-App, Push, SMS | High | Consumer Protection Act |
| EMI due T-7 | Push, In-App | Low | Proactive |
| EMI due T-1 | Push, SMS, WhatsApp | High | Proactive |
| **Auto-pay pre-debit T-2** | **SMS, Email, Push** | **Critical** | **Mandatory — RBI E-Mandate Framework** |
| Auto-pay debit succeeded | Push, SMS, Email | High | Statutory |
| Auto-pay debit failed | Push, SMS, WhatsApp | Critical | Immediate alert |
| Suspicious login / new device | SMS, Email, Push | Critical | RBI Cyber Security Mandate |

**Transactional alerts (OTP, payment confirmations, pre-debit notices) cannot be
disabled by the user.** Preference controls apply to marketing and low-priority only.

---

## 12. RBAC (PRD §15)

| Capability | User | L1 Support | L2 Risk/Recon | L3 Super Admin |
|---|:--:|:--:|:--:|:--:|
| View own dashboard & cards | ✅ | ❌ | ❌ | ❌ |
| Add / delete own cards & accounts | ✅ | ❌ | ❌ | ❌ |
| Initiate transfers & EMI payments | ✅ | ❌ | ❌ | ❌ |
| View masked user profiles & logs | ❌ | ✅ | ✅ | ✅ |
| View raw PII / KYC documents | ❌ | ❌ | ✅ *(audited)* | ✅ *(audited)* |
| Trigger manual reversals | ❌ | ❌ | ✅ | ✅ |
| Override recon discrepancy | ❌ | ❌ | ✅ | ✅ |
| Manage API keys & partners | ❌ | ❌ | ❌ | ✅ |
| Direct production DB access | ❌ | ❌ | ❌ | **❌ (zero-DB)** |
| View system audit logs | ❌ | ❌ | ✅ | ✅ |

Admin modules: user 360° viewer · transaction telemetry · failed-transaction &
reversal queue *(maker-checker mandatory above ₹25,000)* · reconciliation console ·
fraud & risk rules · immutable audit log viewer.

---

## 13. Security & compliance

### 13.1 Non-negotiable rules

1. **Zero raw card storage.** No PAN, CVV, or PIN ever enters CashU — not in the
   database, not in logs, not in an exception trace. Tokenization happens
   client → licensed Token Requestor, never through the backend.
2. **Payments are credited only on a verified gateway signature.** Never on client
   assertion. *(This exact vulnerability existed in the stockverse wallet and was
   patched — it must not be reintroduced here.)*
3. **Third-party bank transfers are prohibited.** Destination accounts must be
   penny-drop verified as belonging to the authenticated user (PMLA).
4. **Credit cards cannot pay loan EMIs.** Server-enforced.
5. **Idempotency key required** on every money-moving request, `UNIQUE`-enforced.
6. **Financial rows are append-only.** Corrections are compensating entries.
7. **PII encrypted at rest** — AES-256-GCM field-level (PAN, Aadhaar, account numbers,
   card tokens, cardholder name).
8. **Every admin mutation writes an audit row** with actor, IP, timestamp, before/after.

### 13.2 Rate limits (PRD §17.1)

| Endpoint class | Limit |
|---|---|
| Public auth | 5 req/min per IP |
| Transaction initiation | 3 req/min per user |
| OTP resend | 3 per 15-min rolling window per IP/device |
| Velocity guard | >3 transfers in 1 hour → throttle + security alert (ERR-011) |

### 13.3 Compliance checklist (PRD §18)

| Area | Requirement | v1 status |
|---|---|---|
| RBI CoFT | Network tokenization via licensed requestor | Adapter built; **vendor unsigned** |
| Credit Card Master Direction | Approved MCC / merchant model for transfers | **⛔ UNRESOLVED — see §16** |
| DPDPA 2023 | Granular consent, right to erasure, data localization | Consent + erasure in v1 |
| PCI DSS v4.0 | SAQ-A profile (no cardholder data touched) | Architecturally satisfied |
| KYC / AML | Min KYC to onboard; Full KYC before transfers >₹10,000 | Tiering in v1 |
| NPCI e-Mandate | AFA at registration, T-24h pre-debit notice, user pause/cancel | In v1 |
| BBPS | Route via licensed BBPOU or registered Agent Institution | Adapter built; **vendor unsigned** |
| PA/PG licensing | Partner with licensed PA; hold no client funds | Architecture holds no funds ✅ |

---

## 14. Vendor adapter seams

All nine PRD §21 integrations are **"To Be Confirmed"**. v1 therefore builds every
external dependency behind an interface with a sandbox implementation, following the
`EMIProviderAdapter` pattern the PRD already mandates (§10.1).

| Interface | Sandbox v1 behaviour | Real candidates |
|---|---|---|
| `TokenRequestorAdapter` | Generates a fake token ref; derives issuer/network from BIN table; simulates 3DS | Juspay Hyperswitch, Razorpay TokenHQ, Cashfree |
| `PaymentGatewayAdapter` | Simulated 3DS challenge + signed webhook | Razorpay, Cashfree, Juspay, PayU |
| `PayoutAdapter` | Simulated IMPS with synthetic UTR; configurable failure injection | ICICI Composite, Cashfree Payouts, Decentro, Setu |
| `PennyDropAdapter` | Returns a configurable CBS name to exercise match/mismatch paths | Decentro, Setu, Cashfree, Karza |
| `EMIProviderAdapter` | Bajaj Finance sandbox — biller lookup, dues, payment ack | BBPS BOU, Bajaj B2B direct |
| `MandateAdapter` | Simulated UMN issue, scheduled debit, bounce injection | Razorpay AutoPay, Cashfree, NPCI ONMAG |
| `KYCAdapter` | Manual admin review queue | Bureau.id, Karza, Signzy, IDfy |
| `SMSAdapter` | Console/log sink | Gupshup, Exotel, Karix |
| `PushAdapter` | No-op in v1 (P1 feature) | FCM, OneSignal |

**Design constraint:** swapping a sandbox for a live vendor must touch exactly one
adapter file plus configuration. If it touches a route or a model, the seam was wrong.

**Failure injection is a v1 requirement**, not a testing luxury — the PRD's §20 error
matrix and §9.4 circuit breaker cannot be verified any other way.

---

## 15. Build order

| Phase | Deliverable | Vendor-blocked? |
|---|---|---|
| **0** | Skeleton: `portal/` package, config, extensions, logger, health, Docker up, seeders | No |
| **1** | Identity: roles, users, OTP, MPIN, JWT, device binding, sessions, rate limits | No |
| **2** | Profile + KYC tiering + admin review queue | No |
| **3** | **Ledger engine + master transactions + self-audit job** — *before any money moves* | No |
| **4** | Card linking via `TokenRequestorAdapter` sandbox; card detail; unlink | Sandbox |
| **5** | Bank accounts + penny-drop sandbox + name matching | Sandbox |
| **6** | Home dashboard aggregation (FR-002) | No |
| **7** | Transfer engine: fee calc, risk/velocity, state machine, idempotency, circuit breaker | Sandbox |
| **8** | EMI registry + Bajaj sandbox adapter + manual payment | Sandbox |
| **9** | Mandate engine + pre-debit scheduler + retry ladder | Sandbox |
| **10** | Notification engine + templates + preferences | Partial |
| **11** | Transaction history, receipts, reconciliation console | No |
| **12** | Admin console + RBAC + audit viewer | No |
| **13** | Frontend polish — motion, empty states, error copy, success moment | No |
| **14** | Test suite against §25 Gherkin criteria + §20 error matrix | No |
| **15** | Production hardening — only once vendors are signed | **Yes** |

**Phase 3 before Phase 4 is deliberate.** The ledger must exist and be provably correct
before anything writes to it.

---

## 16. Open decisions — blocking

Carried from PRD §27. Items 1 and 4 block *launch*, not development.

| # | Decision | Impact | Status |
|---|---|---|---|
| 1 | **Transfer merchant model** — which MCC and legal construct? Escrow, rental/vendor pay with invoice proof, or NBFC co-lending? | **Legal — the whole FR-006 pillar** | ⛔ Open |
| 2 | BBPS integration — direct Agent Institution via licensed BBPOU, or Bajaj B2B tie-up? | Regulatory / Ops | ⛔ Open |
| 3 | Token Requestor partner — must support all four networks | Architecture | ⛔ Open |
| 4 | KYC tiering — is Min KYC acceptable up to ₹10,000, or Full eKYC before any payout? | Compliance | ⛔ Open |
| 5 | Fee absorption — pass 1.95% through, or zero-fee first ₹5,000 for acquisition? | Unit economics | ⛔ Open |
| 6 | Cross-border / NRI cards | Legal | ✅ Closed — domestic INR only |
| 7 | Chargeback liability post-IMPS payout — recovery mechanism? | Risk / Finance | ⛔ Open |

**Additional decisions this document raises:**

| # | Decision | Recommendation |
|---|---|---|
| 8 | MySQL vs PostgreSQL (⚑ D1) | MySQL per your call. Revisit only if the self-audit job shows ledger drift under load. |
| 9 | Redis in v1 (⚑ D2) | Skip. The `UNIQUE` idempotency index is stronger than a Redis TTL. Add Redis when read latency demands it. |
| 10 | UUID vs integer PKs (⚑ D6) | UUID on financial entities. Diverges from stockverse, but enumerable transfer IDs are a real leak. |

---

## 17. Acceptance criteria

v1 is done when the PRD §25 Gherkin scenarios pass against the sandbox adapters:

- **AC-001** Tokenized card linking — token ref received, **zero raw PAN/CVV in the
  database**, masked card appears, confirmation SMS dispatched
- **AC-002** Transfer with fee disclosure — ₹10,000 principal shows ₹200 fee + ₹36 GST
  = ₹10,236 charged, ₹10,000 disbursed, `INITIATED → SUCCEEDED`, ledger entry written
- **AC-003** Pre-debit notification — T-48h SMS + Email containing UMN, amount, date,
  biller name; audit row recorded
- **AC-004** Idempotency — duplicate key within 60s returns the original transaction,
  **no second card charge**

Plus: all 11 §20 error scenarios reproducible via failure injection, and the nightly
ledger self-audit passing on a seeded dataset with reversals.

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
| MySQL | `localhost:3307` — root / Mahesh2605 / `cashu_db` |

MySQL binds host port **3307**, not 3306, because 3306 is already taken by the native
install serving the stockverse project.

---

*End of CashU Version 1 Specification. Derived from PRD v1.0.0-PROD-SPEC.*
