# CashU

Unified credit card and EMI management platform for the Indian market.
Implements the PRD (`CredFlow / Unified Credit & EMI Hub`, v1.0.0-PROD-SPEC).

**React + Tailwind** web app · **Flask** API · **MySQL** · **Cashfree** payments

---

## What it does

Three pillars, per the PRD:

1. **See** — link credit cards via RBI Card-on-File tokenisation and track every
   limit, due date and utilisation figure in one dashboard.
2. **Service** — pay NBFC loan EMIs through BBPS, or arm an NPCI e-Mandate so
   they pay themselves.
3. **Access** — move credit-card headroom to a verified bank account, with the
   fee disclosed before authorisation.

Plus a four-tier RBAC operations console for KYC review, stuck-transfer triage
and ledger reconciliation.

---

## Running it

### Prerequisites
MySQL 8, Python 3.12+, Node 20+.

### Backend

```bash
cd backend
python -m venv venv
venv/Scripts/activate          # Windows;  source venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env           # then fill in the values below
python app.py                  # http://localhost:5050
```

`.env` essentials:

```
DATABASE_URL=mysql+pymysql://root:<password>@localhost:3306/cashu_db
FIELD_ENCRYPTION_KEY=<32 random bytes, base64>
USE_SANDBOX_ADAPTERS=True
```

Generate the encryption key with:

```bash
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

> **Keep this key.** Every PAN, Aadhaar, bank account number and loan account
> number is AES-256-GCM encrypted with it. Lose it and those columns are
> permanently unreadable.

Tables are created and seeded on first boot. Both are idempotent.

### Frontend

```bash
cd frontend
npm install
npm run dev                    # http://localhost:3000
```

The dev server proxies `/v1` to Flask, so the browser sees a single origin.

### Docker

```bash
docker compose up --build
```

Brings up MySQL 8.4, the API and an nginx-served frontend bundle. MySQL binds
host port **3307** to avoid colliding with a native install on 3306.

---

## Signing in

| | |
|---|---|
| Frontend | http://localhost:3000 |
| API | http://localhost:5050/v1 |
| Swagger | http://localhost:5050/v1/doc/ |
| Health | http://localhost:5050/health |

**Members** sign in with a mobile number and OTP. There is no live SMS gateway
in development, so the API returns the code in the response and the OTP screen
prefills it — guarded on `DEBUG`, so it can never leak from a deployed
environment.

**The seeded administrator** is `9999999999` / MPIN `135790`
(override with `ADMIN_SEED_PHONE` and `ADMIN_SEED_MPIN`). Outside development
the seeder refuses to invent an MPIN rather than shipping a known credential on
an account that can read raw PII.

---

## Verifying it works

```bash
cd backend
python tests/smoke_flow.py     # server must be running
```

Walks the full journey — onboarding, KYC submission, admin approval, card
tokenisation, penny-drop verification, transfer, EMI payment — and asserts the
PRD acceptance criteria that carry money:

- **AC-001** tokenised card linking with zero raw PAN stored
- **AC-002** fee arithmetic: ₹10,000 → ₹195 fee + ₹35.10 GST = ₹10,230.10 charged
- **AC-004** a replayed idempotency key returns the original, never a second charge
- **ERR-001** debit and prepaid cards refused
- **PRD 11.1** credit cards refused as an EMI payment instrument

---

## Architecture

```
CashU/
├── backend/                 Flask API (mirrors the stockverse house layout)
│   ├── app.py               entry point; create_all + seeders on boot
│   ├── config/config.py     environment configuration
│   ├── portal/
│   │   ├── __init__.py      InitApp factory, APP singleton, db
│   │   ├── api/             flask-restx Api on the /v1 blueprint
│   │   ├── helpers/         the engines — see below
│   │   ├── models/          28 models, one per file
│   │   ├── routes/          15 namespaces, one package each
│   │   ├── seeders/         idempotent, dependency-ordered
│   │   └── scheduler.py     APScheduler jobs
│   └── tests/
└── frontend/                React + Vite + Tailwind
    └── src/{api,app,components,context,hooks,pages,utils}
```

### The engines

| Module | Owns |
|---|---|
| `ledger_engine` | **The only writer of transactions and ledger rows.** Posting, reversal, nightly self-audit |
| `transfer_engine` | FR-006 state machine, payout retry ladder, circuit breaker |
| `mandate_engine` | e-Mandate registration, T-48h pre-debit notices, 3-rung retry ladder |
| `emi_engine` | EMI collection, biller submission, PENDING polling |
| `risk_engine` | Limits, KYC gating, velocity, per-user rate limits |
| `fee_calculator` | Convenience fee and GST (AC-002) |
| `adapters` | Vendor seam — sandbox and Cashfree behind one interface |
| `cashfree` | PG, Payouts and Verification REST client |
| `name_match` | Penny-drop name scoring |
| `encryption` | AES-256-GCM field encryption, PBKDF2 secrets |

---

## Things that are deliberate

**Sandbox by default.** All nine PRD §21 vendor integrations are still "To Be
Confirmed", so every external rail runs simulated unless
`USE_SANDBOX_ADAPTERS=False` *and* Cashfree credentials are present. The
simulator injects failures on demand — the §20 error matrix and the §9.4
circuit breaker are untestable against a rail that always succeeds.

**One ledger writer.** The PRD specifies PostgreSQL with serializable
isolation; this runs on MySQL, so the balancing guarantee comes from
application structure instead. Everything funnels through
`ledger_engine.post()`, every posting is validated to balance before it flushes,
and a nightly self-audit re-verifies the whole ledger. An `UNBALANCED_LEDGER`
finding means the engine was bypassed — the most severe bug this platform can
have.

**Idempotency is a database constraint,** not a cache entry. The PRD puts it in
Redis with a 24-hour TTL; a `UNIQUE` index cannot be lost to an eviction or a
restart.

**Rules enforced structurally, not by checks.** A credit card cannot pay a loan
EMI because `CREDIT_CARD` is absent from the `PaymentMode` vocabulary. Ledger
rows cannot be deleted because those models have no `delete()`. Neither depends
on a caller remembering.

**Webhooks are hints.** Signature and timestamp are verified over the raw body
before it is parsed, and the gateway's own API is then re-queried before any
money moves. A valid signature proves the body was not altered in transit — not
that a payment settled.

---

## Not yet wired

These need a signed vendor before they can be switched on:

- Card tokenisation needs a licensed Token Requestor (PRD open decision 3)
- BBPS needs a licensed operating unit or a Bajaj B2B tie-up (decision 2)
- SMS needs a DLT-registered gateway
- Push (FCM/APNS) is Phase 1.1

And one that needs a lawyer, not an engineer: **FR-006's merchant model is
unresolved** (PRD open decision 1). RBI's Credit Card Master Direction prohibits
disguised P2P cash cycling, and the MCC and legal construct for credit-to-bank
transfer are still open. The `CREDIT_TO_BANK_TRANSFER` feature flag exists so
the whole capability can be switched off from the admin console without a
deploy, the moment compliance says so.

See `version1.md` §16 for the full decision log.
