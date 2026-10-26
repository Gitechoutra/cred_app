import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { normaliseCard } from '../domain/cardThemes';
import { Badge, Button, Sheet } from '../ui';
import { useToast } from '../../context/ToastContext';
import { date, dateTime, money } from '../../utils/format';

/** The data-source line every card carries. */
export function DataSourceBadge({ card }) {
  const manual = card.kind === 'MANUAL';
  return (
    <Badge tone={manual ? 'warn' : 'neutral'}>
      {manual ? 'User-entered - Not Bank Verified' : 'Limit set by CashU'}
    </Badge>
  );
}

/** Limit, available, outstanding, utilisation and dues for one card. */
export function CardFigures({ card: raw }) {
  const card = normaliseCard(raw);
  const cell = (label, value) => (
    <div className="min-w-0">
      <p className="text-2xs uppercase tracking-wider text-slate">{label}</p>
      <p className="money mt-0.5 truncate text-sm font-semibold text-ink">{value}</p>
    </div>
  );
  const amount = (v) => (v != null ? money(v) : '—');
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
      {cell('Credit limit', amount(card.limit))}
      {cell(card.available_is_derived ? 'Available (worked out)' : 'Available', amount(card.available))}
      {cell('Outstanding', amount(card.outstanding))}
      {cell('Utilisation', card.utilization_percentage != null ? `${card.utilization_percentage}%` : '—')}
      {cell('Minimum due', amount(card.minimumDue))}
      {cell('Due date', card.dueDate ? date(card.dueDate) : '—')}
    </div>
  );
}

/**
 * View, Refresh, Pay bill and (manual cards only) Remove.
 *
 * Refresh re-reads the server's record - CashU's own for a linked card, the
 * holder's figures for a manual one - and says which; nothing is invented.
 * Pay bill shows what is due and whether it can be paid here: bank card bills
 * need a provider CashU does not have yet, and the sheet says so plainly.
 */
export function CardActions({ card: raw, onChanged, showView = true }) {
  const navigate = useNavigate();
  const toast = useToast();
  const card = normaliseCard(raw);
  const [busy, setBusy] = useState('');
  const [bill, setBill] = useState(null);

  async function refresh() {
    setBusy('refresh');
    try {
      const response = card.manual
        ? await endpoints.cards.manual.refresh(card.id)
        : await endpoints.cards.refresh(card.id);
      toast.success(response.message);
      onChanged?.(response.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy('');
    }
  }

  async function openBill() {
    setBusy('bill');
    try {
      const response = await endpoints.cards.bills();
      setBill(response.data.bills.find((b) => b.id === card.id)
        || { pay: response.data.bank_card_payment });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy('');
    }
  }

  async function remove() {
    if (!window.confirm(`Remove ${card.nickname || card.issuer_bank} ending ${card.last4}? Its figures will no longer be shown.`)) return;
    setBusy('remove');
    try {
      const response = await endpoints.cards.manual.remove(card.id);
      toast.success(response.message);
      onChanged?.(null);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {showView && <Button size="sm" variant="outline" onClick={() => navigate(card.path)}>View details</Button>}
        <Button size="sm" variant="outline" loading={busy === 'refresh'} onClick={refresh}>Refresh</Button>
        <Button size="sm" variant="outline" loading={busy === 'bill'} onClick={openBill}>Pay bill</Button>
        {card.manual && (
          <button
            type="button"
            onClick={remove}
            disabled={busy === 'remove'}
            className="h-9 rounded-xl px-4 text-sm font-semibold text-alert transition hover:bg-red-50 disabled:opacity-50"
          >
            {busy === 'remove' ? 'Removing…' : 'Remove'}
          </button>
        )}
      </div>

      <Sheet
        open={Boolean(bill)}
        onClose={() => setBill(null)}
        title={`Bill · ${card.issuer_bank} •• ${card.last4}`}
        footer={bill?.pay?.available ? (
          <Button variant="mint" size="lg" full onClick={() => navigate(bill.pay.route)}>Continue to payment</Button>
        ) : (
          <Button variant="outline" size="lg" full onClick={() => setBill(null)}>Close</Button>
        )}
      >
        {bill && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-2xs uppercase tracking-wider text-slate">Total due</p>
                <p className="money text-xl font-bold text-ink">{bill.total_due != null ? money(bill.total_due) : '—'}</p>
              </div>
              <div>
                <p className="text-2xs uppercase tracking-wider text-slate">Minimum due</p>
                <p className="money text-xl font-bold text-ink">{bill.minimum_due != null ? money(bill.minimum_due) : '—'}</p>
              </div>
            </div>
            <p className="text-sm text-slate">Due {bill.due_date ? date(bill.due_date) : 'date not known'}.</p>
            {bill.data_source_label && <Badge tone={bill.data_source === 'USER_ENTERED' ? 'warn' : 'neutral'}>{bill.data_source_label}</Badge>}
            {!bill.pay?.available && (
              <div className="rounded-xl border border-line bg-mist p-3 text-sm leading-relaxed text-slate">
                {bill.pay?.reason}
              </div>
            )}
          </div>
        )}
      </Sheet>
    </>
  );
}

export function LastUpdated({ card }) {
  return (
    <p className="text-2xs text-slate">
      Last updated {card.last_updated ? dateTime(card.last_updated) : '—'}
    </p>
  );
}
