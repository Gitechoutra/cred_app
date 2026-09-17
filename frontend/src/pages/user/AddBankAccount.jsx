import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Input, Spinner } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useProfile } from '../../hooks/useProfile';
import { money } from '../../utils/format';

/**
 * Add a bank account (PRD FR-005).
 *
 * The account number is entered twice on purpose: a typo here does not fail
 * loudly, it sends money to a real stranger. CashU then verifies ownership by
 * depositing ₹1 and comparing the name the bank returns against the KYC name.
 */
export default function AddBankAccount() {
  const navigate = useNavigate();
  const toast = useToast();
  const { profile } = useProfile();

  const [form, setForm] = useState({
    account_number: '',
    confirm_account_number: '',
    ifsc_code: '',
    account_type: 'SAVINGS',
    account_holder_name: '',
  });
  const [bank, setBank] = useState(null);
  const [matchedAccount, setMatchedAccount] = useState(null);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [lookingUp, setLookingUp] = useState(false);

  const debounce = useRef();

  useEffect(() => {
    if (profile?.full_name && !form.account_holder_name) {
      setForm((current) => ({ ...current, account_holder_name: profile.full_name }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.full_name]);

  // Resolve the IFSC and matching test account as it is typed
  useEffect(() => {
    clearTimeout(debounce.current);
    const ifsc = form.ifsc_code.toUpperCase();

    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc)) {
      setBank(null);
      setMatchedAccount(null);
      return undefined;
    }

    setLookingUp(true);
    debounce.current = setTimeout(async () => {
      try {
        const response = await endpoints.banks.lookupIfsc(ifsc);
        setBank(response.data);
        setErrors((current) => ({ ...current, ifsc_code: '' }));

        // Check if there is a matching test account
        if (form.account_number.length >= 6) {
          try {
            const accRes = await endpoints.banks.lookupAccount({
              account_number: form.account_number,
              ifsc_code: ifsc,
            });
            if (accRes.data) {
              setMatchedAccount(accRes.data);
              if (accRes.data.account_holder_name) {
                setForm((current) => ({
                  ...current,
                  account_holder_name: accRes.data.account_holder_name,
                  account_type: accRes.data.account_type || current.account_type,
                }));
              }
            }
          } catch {
            setMatchedAccount(null);
          }
        }
      } catch {
        setBank(null);
        setMatchedAccount(null);
        setErrors((current) => ({ ...current, ifsc_code: 'We could not find this IFSC code.' }));
      } finally {
        setLookingUp(false);
      }
    }, 400);

    return () => clearTimeout(debounce.current);
  }, [form.ifsc_code, form.account_number]);

  const mismatch =
    form.confirm_account_number.length > 0 &&
    form.account_number !== form.confirm_account_number;

  const valid =
    form.account_number.length >= 6 &&
    !mismatch &&
    form.confirm_account_number.length > 0 &&
    bank;

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: '' }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!valid || loading) return;

    setLoading(true);

    try {
      const response = await endpoints.banks.add({
        ...form,
        ifsc_code: form.ifsc_code.toUpperCase(),
        is_primary: true,
      });

      const account = response.data;

      if (account.penny_drop_status === 'VERIFIED') {
        toast.success('Bank account verified.');
      } else {
        toast.info(response.message, { duration: 7000 });
      }

      navigate('/banks', { replace: true });
    } catch (err) {
      if (err.details?.field) setErrors({ [err.details.field]: err.message });
      else toast.error(err.message);
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Add bank account" back="/banks" />

        <form onSubmit={submit} className="space-y-4 px-4 pt-4">
          <Input
            label="Account number"
            inputMode="numeric"
            autoFocus
            placeholder="Enter your account number"
            value={form.account_number}
            error={errors.account_number}
            onChange={(event) =>
              update('account_number', event.target.value.replace(/\D/g, '').slice(0, 20))
            }
          />

          <Input
            label="Re-enter account number"
            inputMode="numeric"
            placeholder="Type it again"
            value={form.confirm_account_number}
            error={mismatch ? 'The account numbers do not match.' : errors.confirm_account_number}
            onChange={(event) =>
              update('confirm_account_number', event.target.value.replace(/\D/g, '').slice(0, 20))
            }
            onPaste={(event) => {
              // Pasting defeats the point of a confirmation field.
              event.preventDefault();
              toast.info('Please type your account number again to confirm it.');
            }}
          />

          <Input
            label="IFSC code"
            placeholder="HDFC0001234"
            value={form.ifsc_code}
            maxLength={11}
            error={errors.ifsc_code}
            suffix={lookingUp ? <Spinner className="h-4 w-4 text-slate" /> : null}
            hint={
              bank
                ? `${bank.bank_name}${bank.branch ? ` · ${bank.branch}` : ''}`
                : 'Found on your cheque book or bank app.'
            }
            onChange={(event) => update('ifsc_code', event.target.value.toUpperCase().slice(0, 11))}
          />

          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink">Account type</span>
            <div className="grid grid-cols-2 gap-2">
              {['SAVINGS', 'CURRENT'].map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => update('account_type', type)}
                  className={[
                    'h-12 rounded-xl border text-sm font-medium transition',
                    form.account_type === type
                      ? 'border-mint bg-mint-50 text-ink ring-2 ring-mint/25'
                      : 'border-line text-slate hover:border-ink/20',
                  ].join(' ')}
                >
                  {type === 'SAVINGS' ? 'Savings' : 'Current'}
                </button>
              ))}
            </div>
          </div>

          <Input
            label="Account holder name"
            hint="Must match the name registered with your bank."
            value={form.account_holder_name}
            error={errors.account_holder_name}
            onChange={(event) => update('account_holder_name', event.target.value)}
          />

          <div className="rounded-xl bg-mist px-3.5 py-3">
            <p className="text-xs font-medium text-ink">How we verify this account</p>
            <p className="mt-1 text-xs leading-relaxed text-slate">
              We deposit ₹1 and read back the account holder name your bank has on
              record. If it matches your KYC name, the account is verified
              instantly. Transfers can only ever go to an account proven to be
              yours.
            </p>
          </div>

          {matchedAccount && (
            <div className="rounded-xl border border-mint-200 bg-mint-50/70 p-3.5 space-y-2 text-xs">
              <div className="flex items-center justify-between border-b border-mint-200 pb-1.5">
                <span className="font-semibold text-mint-800">Verified Test Account Details</span>
                <span className="rounded-full bg-mint-100 px-2 py-0.5 text-2xs font-semibold text-mint-800">
                  {matchedAccount.account_type}
                </span>
              </div>
              <div className="space-y-1 text-slate">
                <div className="flex justify-between">
                  <span>Bank / Institution:</span>
                  <span className="font-medium text-ink">{matchedAccount.bank_name}</span>
                </div>
                {matchedAccount.branch_name && (
                  <div className="flex justify-between">
                    <span>Branch:</span>
                    <span className="font-medium text-ink">{matchedAccount.branch_name}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span>Account Holder:</span>
                  <span className="font-medium text-ink">{matchedAccount.account_holder_name}</span>
                </div>
                <div className="flex justify-between">
                  <span>Masked Account:</span>
                  <span className="font-mono text-ink">{matchedAccount.masked_account}</span>
                </div>
                <div className="flex justify-between">
                  <span>Available Balance:</span>
                  <span className="font-mono font-semibold text-mint-800">{money(matchedAccount.balance)}</span>
                </div>
              </div>
            </div>
          )}

          <Button type="submit" variant="mint" size="lg" full disabled={!valid} loading={loading}>
            {loading ? 'Verifying…' : 'Add and verify'}
          </Button>
        </form>
      </div>
    </div>
  );
}
