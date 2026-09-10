/**
 * src/api/transfers.js
 * ====================
 * The transfer flow (PRD FR-006), as the screens need it.
 *
 * A thin layer over `endpoints` in client.js rather than a second API client.
 * It exists for two reasons that the generic endpoint map deliberately does not
 * cover:
 *
 * 1. **Unwrapping.** `api.*` returns the whole `{success, message, data}`
 *    envelope. Screens want the payload, so it is unwrapped once here instead
 *    of `.data` being sprinkled through every component.
 *
 * 2. **Idempotency scoped to the user's intent.** `endpoints.transfers.initiate`
 *    goes through `api.pay`, which mints a fresh key per call - correct for a
 *    one-shot payment, wrong for a Continue button the user may press again
 *    after a timeout. Here the caller owns the key, so a retry replays the
 *    original and the backend returns the existing transfer instead of opening
 *    a second one against the same card.
 *
 * The order of operations is fixed by the backend state machine:
 *
 *     quote -> initiate -> [Cashfree 3DS] -> confirm -> poll
 */

import { api, endpoints } from './client';

/** Envelope in, payload out. */
const unwrap = (response) => response?.data ?? response;

/** Fee, GST and remaining headroom for an amount. Reserves nothing. */
export async function quoteTransfer(amount) {
  return unwrap(await endpoints.transfers.quote(amount));
}

/** Limits, usage, and whether the feature flag is open for this user. */
export async function getTransferLimits() {
  return unwrap(await endpoints.transfers.limits());
}

/**
 * Open a transfer and get the Cashfree payment session.
 *
 * Charges nothing. The card is debited only once Cashfree confirms an
 * authenticated payment, and the backend learns about it by webhook.
 */
export async function initiateTransfer({ cardId, bankAccountId, amount, idempotencyKey }) {
  const response = await api.post(
    '/transfers',
    { card_id: cardId, bank_account_id: bankAccountId, amount },
    { idempotent: idempotencyKey },
  );
  return unwrap(response);
}

/**
 * Confirm after the 3DS challenge returns.
 *
 * Belt and braces alongside the Cashfree webhook - whichever reaches the
 * backend first resolves the transfer and the second is a no-op. This proves
 * nothing on its own; the backend re-queries Cashfree before moving any money.
 */
export async function confirmTransfer(transferId) {
  return unwrap(await endpoints.transfers.confirm(transferId));
}

export async function getTransfer(transferId) {
  return unwrap(await endpoints.transfers.get(transferId));
}

export async function getTransferReceipt(transferId) {
  return unwrap(await endpoints.transfers.receipt(transferId));
}

export async function listTransfers(page = 1) {
  // Paginated responses carry `pagination` alongside `data`, so the envelope is
  // returned whole here rather than unwrapped.
  return endpoints.transfers.list(page);
}

/* ── The two instruments a transfer needs ──────────────────────────────── */

export async function listCards() {
  return unwrap(await endpoints.cards.list());
}

export async function listBankAccounts() {
  return unwrap(await endpoints.banks.list());
}

/**
 * Only a penny-drop verified account may receive a payout.
 *
 * The backend enforces this too - it is a PMLA control, not a UI nicety - but
 * filtering here means the user never picks a destination that will be refused
 * after they have already authenticated the card charge.
 */
export function payoutEligible(accounts = []) {
  return accounts.filter((account) => account.is_payout_eligible);
}

/* ── Status helpers ────────────────────────────────────────────────────── */

/** Statuses the backend will not move a transfer out of. */
export const TERMINAL_STATUSES = [
  'RISK_FAILED',
  'SUCCEEDED',
  'REVERSED_TO_CARD',
  'FAILED',
];

export function isTerminal(status) {
  return TERMINAL_STATUSES.includes(status);
}
