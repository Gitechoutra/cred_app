import { useState } from 'react';

import { SUPPORTED_BANKS } from '../../data/supportedBanks';
import { CardTile } from '../domain';
import { Button, Input, cx } from '../ui';

const NETWORKS = ['VISA', 'MASTERCARD', 'RUPAY', 'AMEX', 'DINERS', 'OTHER'];
const OTHER_BANK = '__other__';

const MONEY_FIELDS = [
  ['credit_limit', 'Total credit limit'],
  ['outstanding_balance', 'Outstanding balance'],
  ['available_credit', 'Available credit'],
  ['total_due', 'Total amount due'],
  ['minimum_due', 'Minimum amount due'],
];

function toForm(card) {
  const known = SUPPORTED_BANKS.find((b) => b.id === card?.issuer_id || b.name === card?.issuer_bank);
  const form = {
    bank: card ? (known ? known.id : OTHER_BANK) : '',
    otherBank: card && !known ? card.issuer_bank : '',
    nickname: card?.nickname || '',
    network: card?.network || 'VISA',
    last4: card?.last4 || '',
    statement_day: card?.statement_day ? String(card.statement_day) : '',
    payment_due_date: card?.payment_due_date || '',
  };
  MONEY_FIELDS.forEach(([key]) => { form[key] = card?.[key] != null ? String(card[key]) : ''; });
  // A worked-out available figure is not something the holder entered.
  if (card?.available_is_derived) form.available_credit = '';
  return form;
}

/**
 * Add or edit a card by hand.
 *
 * Asks for the bank, the last four digits and whatever figures the holder
 * knows - never the card number, CVV, expiry, PIN, OTP or a bank password.
 * The server checks everything again; checks here only save a round trip.
 */
export default function ManualCardForm({ card, onSubmit, submitLabel = 'Save card', busy = false, serverError }) {
  const [form, setForm] = useState(() => toForm(card));
  const [errors, setErrors] = useState({});
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const bank = SUPPORTED_BANKS.find((b) => b.id === form.bank);
  const bankName = form.bank === OTHER_BANK ? form.otherBank.trim() : bank?.name || '';
  const fieldError = (name) => errors[name] || (serverError?.field === name ? serverError.message : '');

  function validate() {
    const found = {};
    if (!bankName) found[form.bank === OTHER_BANK ? 'otherBank' : 'bank'] = 'Choose the issuing bank.';
    if (!/^\d{4}$/.test(form.last4)) found.last4 = 'Enter the last four digits.';
    MONEY_FIELDS.forEach(([key]) => {
      if (form[key] && !/^\d{1,10}(\.\d{1,2})?$/.test(form[key])) found[key] = 'Enter an amount like 25000 or 25000.50.';
    });
    const n = (k) => (form[k] ? Number(form[k]) : null);
    if (n('credit_limit') === 0) found.credit_limit = 'A credit limit must be more than zero.';
    if (n('credit_limit') != null && n('available_credit') != null && n('available_credit') > n('credit_limit')) {
      found.available_credit = 'Cannot be more than the credit limit.';
    }
    if (n('minimum_due') != null && n('total_due') != null && n('minimum_due') > n('total_due')) {
      found.minimum_due = 'Cannot be more than the total due.';
    }
    if (form.statement_day && !(Number(form.statement_day) >= 1 && Number(form.statement_day) <= 31)) {
      found.statement_day = 'A day between 1 and 31.';
    }
    setErrors(found);
    return Object.keys(found).length === 0;
  }

  function submit(event) {
    event.preventDefault();
    if (busy || !validate()) return;
    const body = {
      issuer_bank: bankName,
      issuer_id: form.bank && form.bank !== OTHER_BANK ? form.bank : null,
      nickname: form.nickname.trim() || null,
      network: form.network,
      last4: form.last4,
      statement_day: form.statement_day ? Number(form.statement_day) : null,
      payment_due_date: form.payment_due_date || null,
    };
    MONEY_FIELDS.forEach(([key]) => { body[key] = form[key] || null; });
    onSubmit(body);
  }

  const preview = {
    kind: 'MANUAL',
    issuer_bank: bankName || 'Your bank',
    issuer_id: form.bank !== OTHER_BANK ? form.bank : null,
    nickname: form.nickname,
    network: form.network,
    masked_pan: `**** **** **** ${form.last4.padEnd(4, '•')}`,
    credit_limit: form.credit_limit ? Number(form.credit_limit) : null,
    available_credit: form.available_credit
      ? Number(form.available_credit)
      : (form.credit_limit && form.outstanding_balance
        ? Math.max(0, Number(form.credit_limit) - Number(form.outstanding_balance)) : null),
    utilization_percentage: form.credit_limit && form.outstanding_balance
      ? Math.round((Number(form.outstanding_balance) / Number(form.credit_limit)) * 1000) / 10 : null,
    payment_due_date: form.payment_due_date,
    theme: card?.theme || 'AUTO',
    status: 'ACTIVE',
  };

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <CardTile card={preview} />

      <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
        <span className="font-bold">User-entered - Not Bank Verified.</span> These are
        your own figures. CashU shows them as you typed them and never treats them as
        confirmed by your bank. Do not enter your card number, CVV, expiry or any PIN or OTP.
      </div>

      <div>
        <label htmlFor="mc-bank" className="mb-1.5 block text-sm font-medium text-ink">Issuing bank</label>
        <select
          id="mc-bank"
          value={form.bank}
          onChange={(e) => set({ bank: e.target.value })}
          className={cx(
            'h-12 w-full rounded-xl border bg-canvas px-3 text-[15px] text-ink outline-none focus:ring-2 focus:ring-mint/20',
            fieldError('bank') ? 'border-alert' : 'border-line',
          )}
        >
          <option value="">Choose a bank</option>
          {SUPPORTED_BANKS.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          <option value={OTHER_BANK}>Another bank</option>
        </select>
        {fieldError('bank') && <p className="mt-1 text-xs text-alert">{fieldError('bank')}</p>}
      </div>
      {form.bank === OTHER_BANK && (
        <Input label="Bank name" value={form.otherBank} maxLength={150}
          error={fieldError('otherBank') || fieldError('issuer_bank')}
          onChange={(e) => set({ otherBank: e.target.value })}
        />
      )}

      <div className="grid grid-cols-2 gap-3">
        <Input label="Last four digits" inputMode="numeric" maxLength={4} placeholder="4821"
          value={form.last4} error={fieldError('last4')}
          onChange={(e) => set({ last4: e.target.value.replace(/\D/g, '').slice(0, 4) })}
        />
        <div>
          <label htmlFor="mc-network" className="mb-1.5 block text-sm font-medium text-ink">Card type</label>
          <select id="mc-network" value={form.network} onChange={(e) => set({ network: e.target.value })}
            className="h-12 w-full rounded-xl border border-line bg-canvas px-3 text-[15px] text-ink outline-none focus:ring-2 focus:ring-mint/20"
          >
            {NETWORKS.map((n) => <option key={n} value={n}>{n === 'AMEX' ? 'American Express' : n[0] + n.slice(1).toLowerCase()}</option>)}
          </select>
        </div>
      </div>

      <Input label="Nickname" hint="Optional, e.g. Travel card" maxLength={100}
        value={form.nickname} error={fieldError('nickname')}
        onChange={(e) => set({ nickname: e.target.value })}
      />

      <p className="pt-1 text-2xs font-semibold uppercase tracking-wider text-slate">Figures you know (all optional)</p>
      <div className="grid grid-cols-2 gap-3">
        {MONEY_FIELDS.map(([key, label]) => (
          <Input key={key} label={label} prefix="₹" inputMode="decimal"
            hint={key === 'available_credit' ? 'Left empty, worked out from limit and balance' : undefined}
            value={form[key]} error={fieldError(key)}
            onChange={(e) => set({ [key]: e.target.value.replace(/[^\d.]/g, '') })}
          />
        ))}
        <Input label="Statement day" hint="Day of month" inputMode="numeric" maxLength={2}
          value={form.statement_day} error={fieldError('statement_day')}
          onChange={(e) => set({ statement_day: e.target.value.replace(/\D/g, '').slice(0, 2) })}
        />
      </div>
      <Input label="Payment due date" type="date" value={form.payment_due_date}
        error={fieldError('payment_due_date')}
        onChange={(e) => set({ payment_due_date: e.target.value })}
      />

      {serverError && !serverError.field && (
        <p className="text-sm text-alert" role="alert">{serverError.message}</p>
      )}

      <Button type="submit" variant="mint" size="lg" full loading={busy}>{submitLabel}</Button>
    </form>
  );
}
