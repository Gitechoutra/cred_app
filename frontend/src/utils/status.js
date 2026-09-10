/**
 * Transfer status presentation.
 *
 * The tone rule from version1.md 3.2: never scold, always state the cause and
 * the next action. A reversal is not a failure the user caused, and the copy
 * says so - their money is coming back.
 */

export const STATUS_LABELS = {
  INITIATED: 'Starting',
  RISK_CHECKED: 'Checks passed',
  RISK_FAILED: 'Could not proceed',
  AUTH_PENDING: 'Awaiting authentication',
  INBOUND_CHARGED: 'Card charged',
  PAYOUT_PROCESSING: 'Sending to your bank',
  SUCCEEDED: 'Completed',
  PENDING_RECONCILIATION: 'Under review',
  REVERSAL_INIT: 'Refunding',
  REVERSED_TO_CARD: 'Refunded to your card',
  FAILED: 'Did not complete',
};

/** mint = done, warn = in flight, alert = needs attention, slate = neutral. */
export const STATUS_TONE = {
  SUCCEEDED: 'mint',
  REVERSED_TO_CARD: 'warn',
  RISK_FAILED: 'alert',
  FAILED: 'alert',
  PENDING_RECONCILIATION: 'warn',
  PAYOUT_PROCESSING: 'warn',
  INBOUND_CHARGED: 'warn',
  AUTH_PENDING: 'warn',
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || 'Unknown';
}

export function statusTone(status) {
  return STATUS_TONE[status] || 'slate';
}
