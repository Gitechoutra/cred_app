"""
Static audit: the validation rules that are properties of the code and schema
rather than of a running request.

Covers section 17 (security), 18 (API contract), 19 (database) and the parts of
20 (admin) that are about authorization decorators rather than behaviour.

Run from the backend directory:

    python tests/static_audit.py
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(os.path.dirname(BACKEND), 'frontend')


def check(section, label, ok, detail=''):
    RESULTS.append((section, label, bool(ok), detail))
    print(f'  [{"PASS" if ok else "FAIL"}] {label}'
          + (f' - {detail}' if detail and not ok else ''))
    return bool(ok)


def walk(root, suffix):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in ('venv', 'node_modules', '__pycache__', 'dist',
                                '.git', 'migrations')]
        for name in files:
            if name.endswith(suffix):
                yield os.path.join(base, name)


def read(path):
    with io.open(path, encoding='utf-8', errors='ignore') as handle:
        return handle.read()


def main():
    print('\nCashU static audit\n' + '=' * 66)

    # ================= 17. Secrets ===================================
    print('\n[17] Secret handling')

    frontend_src = os.path.join(FRONTEND, 'src')
    leaked = []
    for path in walk(frontend_src, '.js'):
        body = read(path)
        if re.search(r'rzp_live_|key_secret|RAZORPAY_KEY_SECRET', body):
            leaked.append(path)
    for path in walk(frontend_src, '.jsx'):
        body = read(path)
        if re.search(r'rzp_live_|key_secret|RAZORPAY_KEY_SECRET', body):
            leaked.append(path)
    check(17, 'no gateway secret referenced in frontend source', not leaked,
          ', '.join(leaked))

    dist = os.path.join(FRONTEND, 'dist')
    bundle_leak = []
    if os.path.isdir(dist):
        for path in walk(dist, '.js'):
            if 'q3QQR8tdzPCAvCtFgarT2Oiv' in read(path):
                bundle_leak.append(path)
    check(17, 'no gateway secret in the built bundle', not bundle_leak,
          ', '.join(bundle_leak))

    env_path = os.path.join(BACKEND, '.env')
    gitignore = os.path.join(BACKEND, '.gitignore')
    ignored = os.path.exists(gitignore) and '.env' in read(gitignore)
    check(17, '.env is gitignored', ignored)

    config = read(os.path.join(BACKEND, 'config', 'config.py'))
    hardcoded = re.findall(r"=\s*'(rzp_(?:test|live)_[A-Za-z0-9]+)'", config)
    check(17, 'no credentials hardcoded in config.py', not hardcoded,
          ', '.join(hardcoded))

    # ================= 17. Password / secret storage =================
    print('\n[17] Credential storage')

    enc = read(os.path.join(BACKEND, 'portal', 'helpers', 'encryption.py'))
    check(17, 'secrets are hashed with a KDF, not stored reversibly',
          'pbkdf2' in enc.lower() or 'bcrypt' in enc.lower()
          or 'scrypt' in enc.lower() or 'argon' in enc.lower())

    models_dir = os.path.join(BACKEND, 'portal', 'models')
    # Type-aware: a credential stored in the clear would be a String column.
    # A Boolean `mpin_set` flag or a DateTime `mpin_last_changed` holds no
    # secret, and flagging them trains the reader to ignore this check.
    plain = []
    for path in walk(models_dir, '.py'):
        body = read(path)
        for match in re.finditer(
            r'(\w*(?:password|passwd|mpin|cvv|card_number|raw_pan)\w*)'
            r'\s*=\s*db\.Column\(\s*db\.(\w+)',
            body, re.I,
        ):
            name, kind = match.group(1), match.group(2)
            if kind.lower() not in ('string', 'text', 'unicode'):
                continue
            if name.lower().endswith(('hash', 'salt', 'algo')):
                continue
            plain.append(f'{os.path.basename(path)}:{name} ({kind})')
    check(17, 'no plaintext password/mpin column', not plain, ', '.join(plain))

    # The issued credit line, specifically. The platform generates the card
    # identity itself, so a full PAN, a CVV or a PIN column here would be
    # something this codebase chose to store rather than something a vendor
    # handed it - and the whole design is that those digits are never composed.
    credit_models = read(os.path.join(models_dir, 'credit_accounts.py'))
    forbidden = []
    for match in re.finditer(r'(\w+)\s*=\s*db\.Column', credit_models):
        name = match.group(1).lower()
        if name in ('card_bin', 'card_last4'):
            continue
        if any(token in name for token in
               ('cvv', 'cvc', 'pin', 'card_number', 'pan', 'full_number',
                'otp', 'password', 'secret', 'track_data', 'magstripe')):
            forbidden.append(match.group(1))
    check(17, 'the credit account stores no PAN, CVV or PIN',
          not forbidden, ', '.join(forbidden))

    # Test transactions must be distinguishable from real ones, and the
    # distinction has to be in the row rather than inferred from an environment
    # that a report will not know about.
    credit_txn_model = read(os.path.join(models_dir, 'credit_transactions.py'))
    check(17, 'a credit transaction records whether it was a test',
          'is_test' in credit_txn_model)

    engine_src = read(os.path.join(BACKEND, 'portal', 'helpers',
                                   'credit_engine.py'))
    check(17, 'test spending is gated by the hardened test-card switch',
          'test_cards.enabled()' in engine_src)

    # ================= 17/20. Authorization coverage =================
    print('\n[17/20] Endpoint authorization')

    routes_dir = os.path.join(BACKEND, 'portal', 'routes')
    unprotected = []
    # Endpoints that are unauthenticated by design.
    public = ('authentication', 'webhooks')

    for path in walk(routes_dir, 'routes.py'):
        module = os.path.basename(os.path.dirname(path))
        if module in public:
            continue
        body = read(path)
        # Each HTTP verb inside a Resource should carry jwt_required.
        #
        # The decorator run is matched by what it is NOT - a blank line, or
        # another decorator's opening @ - rather than by an allowed character
        # set. The previous character class excluded newlines, so a decorator
        # wrapped onto a second line (@roles_required with three role constants,
        # say) ended the run early and hid the @jwt_required above it. Three
        # properly protected admin endpoints were reported as unprotected for
        # exactly that reason.
        for match in re.finditer(
            r'((?:[ \t]*@[^\n]*\n(?:[ \t]+[^@\s][^\n]*\n)*)*)'
            r'[ \t]*def (get|post|put|patch|delete)\(self',
            body,
        ):
            decorators = match.group(1)
            if 'jwt_required' not in decorators:
                line = body[:match.start()].count('\n') + 1
                unprotected.append(f'{module}/routes.py:{line} {match.group(2)}')

    check(17, 'every non-public endpoint requires a JWT', not unprotected,
          '; '.join(unprotected[:6]))

    admin_body = read(os.path.join(routes_dir, 'admin', 'routes.py'))
    admin_verbs = len(re.findall(r'def (get|post|put|patch|delete)\(self',
                                 admin_body))
    admin_rbac = len(re.findall(r'roles_required', admin_body))
    check(20, 'admin endpoints carry an RBAC decorator',
          admin_rbac >= admin_verbs * 0.8,
          f'{admin_rbac} roles_required for {admin_verbs} handlers')

    # ================= 17. Injection surface =========================
    print('\n[17] Injection surface')

    raw_sql = []
    for path in walk(os.path.join(BACKEND, 'portal'), '.py'):
        body = read(path)
        for match in re.finditer(r'text\(\s*f["\']|execute\(\s*f["\']', body):
            line = body[:match.start()].count('\n') + 1
            raw_sql.append(f'{os.path.relpath(path, BACKEND)}:{line}')
    check(17, 'no f-string interpolation into raw SQL', not raw_sql,
          '; '.join(raw_sql[:5]))

    # ================= 19. Database constraints ======================
    print('\n[19] Database schema')

    try:
        from portal import InitApp, db
        from sqlalchemy import inspect as sa_inspect

        app = InitApp().app()
        with app.app_context():
            inspector = sa_inspect(db.engine)
            tables = inspector.get_table_names()

            check(19, 'schema is present', len(tables) > 20, f'{len(tables)} tables')

            # Money must never be float.
            float_money = []
            for table in tables:
                for column in inspector.get_columns(table):
                    name = column['name'].lower()
                    kind = str(column['type']).upper()
                    if any(k in name for k in ('amount', 'balance', 'fee',
                                               'limit', 'principal', 'debit',
                                               'credit')):
                        if 'FLOAT' in kind or 'DOUBLE' in kind or 'REAL' in kind:
                            float_money.append(f'{table}.{column["name"]} ({kind})')
            check(19, 'no money column uses a float type', not float_money,
                  '; '.join(float_money[:5]))

            # Primary keys everywhere.
            no_pk = [t for t in tables
                     if not inspector.get_pk_constraint(t).get('constrained_columns')
                     and t != 'alembic_version']
            check(19, 'every table has a primary key', not no_pk,
                  ', '.join(no_pk))

            # Idempotency and gateway ids must be unique.
            def has_unique(table, column):
                for index in inspector.get_indexes(table):
                    if index.get('unique') and index['column_names'] == [column]:
                        return True
                for uq in inspector.get_unique_constraints(table):
                    if uq['column_names'] == [column]:
                        return True
                cols = {c['name']: c for c in inspector.get_columns(table)}
                return column in cols and cols[column].get('primary_key')

            # Every money table this platform writes. Named explicitly and
            # asserted present, because `if table in tables` quietly turns a
            # dropped or renamed table into a pass rather than a failure.
            # The live schema, not only the model file: a column added by a
            # migration and never modelled would be invisible to a source scan.
            for table in ('credit_accounts', 'credit_transactions'):
                if table not in tables:
                    check(17, f'{table} exists to be audited', False)
                    continue
                offenders = []
                for column in inspector.get_columns(table):
                    name = column['name'].lower()
                    if name in ('card_bin', 'card_last4'):
                        continue
                    if any(token in name for token in
                           ('cvv', 'cvc', 'pin', 'card_number', 'pan',
                            'full_number', 'otp', 'password', 'secret')):
                        offenders.append(column['name'])
                check(17, f'{table} has no sensitive-credential column',
                      not offenders, ', '.join(offenders))

            MONEY_TABLES = ('qr_payments', 'emi_payments', 'master_transactions')

            for table in MONEY_TABLES:
                check(19, f'{table} exists to be audited', table in tables)

            for table, column in [
                ('qr_payments', 'idempotency_key'),
                ('emi_payments', 'idempotency_key'),
                ('emi_payments', 'gateway_payment_id'),
                ('master_transactions', 'idempotency_key'),
            ]:
                if table in tables:
                    check(19, f'{table}.{column} is unique',
                          has_unique(table, column))

            # Financial rows must reference a real user.
            for table in MONEY_TABLES:
                if table in tables:
                    fks = inspector.get_foreign_keys(table)
                    check(19, f'{table} has a foreign key to users',
                          any(fk['referred_table'] == 'users' for fk in fks),
                          str([fk['referred_table'] for fk in fks]))

            # Amounts must not be nullable on a money row.
            for table, column in [('qr_payments', 'amount'),
                                  ('emi_payments', 'amount'),
                                  ('master_transactions', 'gross_amount')]:
                if table in tables:
                    cols = {c['name']: c for c in inspector.get_columns(table)}
                    if column in cols:
                        check(19, f'{table}.{column} is NOT NULL',
                              not cols[column]['nullable'])

    except Exception as exc:
        check(19, 'database inspection ran', False, str(exc)[:160])

    # ================= 19. Transactional integrity ===================
    print('\n[19] Transactional integrity')

    ledger = read(os.path.join(BACKEND, 'portal', 'helpers', 'ledger_engine.py'))
    check(19, 'ledger writes are rolled back on failure',
          'rollback' in ledger)
    check(19, 'ledger enforces a balanced double entry',
          'debit' in ledger and 'credit' in ledger
          and ('!=' in ledger or 'abs(' in ledger))

    qr_engine = read(os.path.join(BACKEND, 'portal', 'helpers',
                                  'qr_payment_engine.py'))
    emi_engine = read(os.path.join(BACKEND, 'portal', 'helpers',
                                   'emi_engine.py'))
    check(19, 'QR payment confirmation locks the row before deciding',
          'with_for_update' in qr_engine)
    check(19, 'EMI confirmation locks the row before deciding',
          'with_for_update' in emi_engine)

    # ================= 11. Razorpay rules ============================
    print('\n[11] Gateway rules')

    rzp = read(os.path.join(BACKEND, 'portal', 'helpers', 'razorpay.py'))
    check(11, 'checkout signature verified with compare_digest',
          'compare_digest' in rzp)
    check(11, 'webhook signature verified with compare_digest',
          rzp.count('compare_digest') >= 2)
    check(11, 'amounts converted through Decimal, never float',
          'Decimal' in rzp and 'ROUND_HALF_UP' in rzp)
    check(11, 'order creation sets payment_capture',
          'payment_capture' in rzp)
    check(11, 'only a captured payment counts as paid',
          "== 'captured'" in rzp or "'captured'" in rzp)

    adapters = read(os.path.join(BACKEND, 'portal', 'helpers', 'adapters.py'))
    check(11, 'an authorized-but-uncaptured payment is treated as pending',
          "'authorized'" in adapters and 'PENDING' in adapters)

    return report()


def report():
    print('\n' + '=' * 66)
    passed = [r for r in RESULTS if r[2]]
    failed = [r for r in RESULTS if not r[2]]
    print(f'{len(passed)} passed, {len(failed)} failed, {len(RESULTS)} total')

    if failed:
        print('\nFAILURES')
        for section, label, _, detail in failed:
            print(f'  [S{section}] {label}' + (f'  ({detail})' if detail else ''))

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
