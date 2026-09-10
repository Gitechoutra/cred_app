/**
 * Rupee formatting.
 *
 * Every amount the backend sends is a plain number of rupees (it does the
 * Decimal maths server-side and hands over floats), so nothing here recomputes
 * a fee - it only presents one. Fee arithmetic lives in fee_calculator.py and
 * must not be duplicated in the client, or the disclosed total and the charged
 * total can drift apart.
 */

const formatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compact = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return formatter.format(Number(value));
}

export function moneyShort(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return compact.format(Number(value));
}

/** "12 Mar 2026, 4:05 pm" — never a bare ISO string in the UI. */
export function formatDateTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date);
}
