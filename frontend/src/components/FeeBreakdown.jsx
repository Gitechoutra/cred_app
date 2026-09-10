import { money } from '../utils/money';

/**
 * The pre-authorisation fee disclosure (PRD FR-006, AC-002).
 *
 * This is a compliance surface, not decoration: the user must see the exact
 * amount their card will be charged, and the exact amount that will reach their
 * bank, *before* the 3DS challenge. So the two totals are the loudest things
 * here and the fee lines sit between them rather than being tucked behind a
 * disclosure toggle.
 *
 * Every figure comes from the backend quote. Nothing is recomputed client-side,
 * because a rounding difference between this and fee_calculator.py would mean
 * disclosing one number and charging another.
 */
export default function FeeBreakdown({ quote, loading = false }) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3" aria-busy="true">
        <div className="h-4 w-2/3 rounded bg-mist" />
        <div className="h-4 w-1/2 rounded bg-mist" />
        <div className="h-10 w-full rounded bg-mist" />
      </div>
    );
  }

  if (!quote) return null;

  const breakdown = quote.breakdown || quote;

  const principal = breakdown.principal_amount;
  const fee = breakdown.convenience_fee;
  const gst = breakdown.gst_on_fee;
  const charged = breakdown.total_charged_to_card;
  const payout = breakdown.net_payout_amount;
  const feePercent = breakdown.fee_percentage_applied;

  return (
    <dl className="space-y-3 text-sm">
      <Row label="Transfer amount" value={money(principal)} />
      <Row
        label={`Convenience fee${feePercent ? ` (${feePercent}%)` : ''}`}
        value={money(fee)}
        muted
      />
      <Row label="GST on fee (18%)" value={money(gst)} muted />

      <div className="border-t border-line pt-3">
        <Row
          label="Charged to your card"
          value={money(charged)}
          emphasis
        />
      </div>

      <div className="rounded-xl bg-mist p-3">
        <Row label="Credited to your bank" value={money(payout)} emphasis />
      </div>
    </dl>
  );
}

function Row({ label, value, muted = false, emphasis = false }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className={muted ? 'text-slate' : 'text-ink'}>{label}</dt>
      <dd
        className={`tabular ${
          emphasis ? 'text-base font-semibold text-ink' : muted ? 'text-slate' : 'text-ink'
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
