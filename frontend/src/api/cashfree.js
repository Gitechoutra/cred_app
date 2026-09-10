/**
 * src/api/cashfree.js
 * ===================
 * The Cashfree Checkout handoff.
 *
 * This is the only place in the app that touches the payment SDK, and the only
 * place that *could* touch card data - so it deliberately does not. The card
 * number, expiry and CVV are typed into Cashfree's own hosted checkout, which
 * this module hands control to via a `payment_session_id`. Nothing sensitive
 * passes through CashU's own code or its backend, which is what keeps the
 * platform inside PCI DSS SAQ-A (PRD section 18).
 *
 * Two paths land here, and the caller does not have to know which is live:
 *
 * - **Live/sandbox Cashfree** - the backend returns a real `payment_session_id`
 *   and the SDK drives the 3DS2 challenge.
 * - **Simulated adapters** (`USE_SANDBOX_ADAPTERS=True`) - the backend has no
 *   Cashfree credentials, so it returns a local `checkout_url` instead and the
 *   app renders its own stand-in challenge screen. That exists so the whole
 *   authorise-confirm-settle flow can be walked before vendor keys arrive.
 */

import { load } from '@cashfreepayments/cashfree-js';

let sdkPromise = null;

/** Cashfree's SDK is a singleton - loading it twice re-injects its iframe. */
function getCashfree() {
  if (!sdkPromise) {
    sdkPromise = load({
      mode: import.meta.env.VITE_CASHFREE_MODE || 'sandbox',
    });
  }
  return sdkPromise;
}

/**
 * True when the backend handed back a locally-rendered stand-in rather than a
 * real Cashfree session.
 */
export function isSimulatedCheckout(transfer) {
  return Boolean(transfer?.three_ds_url?.startsWith('/sandbox/'));
}

/**
 * Hand the user to Cashfree's hosted checkout.
 *
 * Redirects the current tab rather than opening a popup: 3DS challenges are
 * issued by the card's bank, and a meaningful share of Indian issuer pages
 * break inside a popup or an iframe. On success the issuer returns the user to
 * the backend's configured return URL, which carries `transfer_id`.
 *
 * Resolves only if the redirect did not happen; a successful handoff navigates
 * away and nothing after it runs.
 */
export async function openCheckout(transfer) {
  const paymentSessionId = transfer?.payment_session_id;

  if (!paymentSessionId) {
    throw new Error(
      'This transfer has no payment session. It may have already been completed.',
    );
  }

  const cashfree = await getCashfree();

  const result = await cashfree.checkout({
    paymentSessionId,
    redirectTarget: '_self',
  });

  // The SDK reports a refused session here rather than throwing. Surfacing it
  // matters: the alternative is a checkout button that silently does nothing.
  if (result?.error) {
    throw new Error(
      result.error.message || 'Cashfree could not open the payment page.',
    );
  }

  return result;
}
