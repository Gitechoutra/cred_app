/**
 * Formatting helpers.
 *
 * Indian digit grouping throughout: 1,42,850 not 142,850. Getting this wrong is
 * the fastest way to make a fintech feel foreign to the people using it.
 */

export function money(value, { decimals = 2, symbol = true } = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return symbol ? '₹0.00' : '0.00';
  }

  const amount = Number(value);
  const formatted = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(amount));

  const sign = amount < 0 ? '-' : '';
  return `${sign}${symbol ? '₹' : ''}${formatted}`;
}

/** Compact form for dense tiles: ₹1.4L, ₹2.5Cr. */
export function moneyCompact(value) {
  const amount = Number(value) || 0;
  const abs = Math.abs(amount);
  const sign = amount < 0 ? '-' : '';

  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(abs >= 1e8 ? 0 : 1)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(abs >= 1e6 ? 0 : 1)}L`;
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}K`;
  return `${sign}₹${abs.toFixed(0)}`;
}

export function date(value, { withYear = true } = {}) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';

  return d.toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    ...(withYear ? { year: 'numeric' } : {}),
  });
}

export function dateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';

  return d.toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/**
 * Human-scale relative time.
 *
 * "Due in 3 days" tells a user what to do; "10 Sep 2026" makes them work it out.
 */
export function relativeDays(value) {
  if (!value) return null;

  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  target.setHours(0, 0, 0, 0);

  const days = Math.round((target - today) / 86400000);

  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days === -1) return 'Yesterday';
  if (days > 1) return `in ${days} days`;
  return `${Math.abs(days)} days ago`;
}

export function initials(name) {
  if (!name) return 'CU';
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('');
}

/** Group a card number as the user types: 4556 1400 0000 4821. */
export function groupCardNumber(digits) {
  return (digits || '').replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim();
}

export function titleCase(value) {
  if (!value) return '';
  return String(value)
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ── Status vocabulary ──────────────────────────────────────────────────── */

const STATUS_TONES = {
  SUCCEEDED: 'good',
  SETTLED: 'good',
  SUCCESSFUL: 'good',
  ACTIVE: 'good',
  VERIFIED: 'good',
  APPROVED: 'good',
  PAID: 'good',

  PENDING: 'warn',
  PROCESSING: 'warn',
  INITIATED: 'warn',
  AUTH_PENDING: 'warn',
  INBOUND_CHARGED: 'warn',
  PAYOUT_PROCESSING: 'warn',
  PENDING_RECONCILIATION: 'warn',
  UNDER_REVIEW: 'warn',
  PENDING_AFA: 'warn',
  DUE: 'warn',
  IN_PROGRESS: 'warn',
  NAME_MISMATCH: 'warn',
  PAUSED: 'warn',

  FAILED: 'alert',
  RISK_FAILED: 'alert',
  REJECTED: 'alert',
  OVERDUE: 'alert',
  REVERSED: 'alert',
  REVERSED_TO_CARD: 'alert',
  REVERSAL_INIT: 'alert',
  EXPIRED: 'alert',
  REVOKED: 'alert',
  MANUAL_REVIEW_KYC: 'alert',
  SUSPENDED: 'alert',
  FROZEN: 'alert',
};

export function statusTone(status) {
  return STATUS_TONES[status] || 'neutral';
}

const STATUS_LABELS = {
  AUTH_PENDING: 'Awaiting authentication',
  INBOUND_CHARGED: 'Card charged',
  PAYOUT_PROCESSING: 'Sending to bank',
  PENDING_RECONCILIATION: 'Under review',
  REVERSAL_INIT: 'Reversing',
  REVERSED_TO_CARD: 'Refunded to card',
  RISK_FAILED: 'Declined',
  SUCCEEDED: 'Completed',
  SETTLED: 'Paid',
  PENDING_AFA: 'Awaiting bank approval',
  MANUAL_REVIEW_KYC: 'Needs verification',
  NAME_MISMATCH: 'Name mismatch',
  NOT_CONFIGURED: 'Not set up',
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || titleCase(status);
}

const TRANSACTION_LABELS = {
  CARD_TO_BANK_TRANSFER: 'Transfer to bank',
  EMI_MANUAL_PAY: 'EMI payment',
  EMI_AUTO_PAY: 'EMI auto-pay',
  FEE_DEBIT: 'Platform fee',
  REVERSAL_REFUND: 'Refund',
  PENNY_DROP: 'Account verification',
};

export function transactionLabel(type) {
  return TRANSACTION_LABELS[type] || titleCase(type);
}
