import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Loads Razorpay Checkout on demand.
 *
 * The script is fetched when a payment screen mounts rather than in index.html,
 * because most sessions never pay anything and a third-party script on every
 * page is a third-party script on every page.
 *
 * Loading is deduplicated against the document: a user who navigates between
 * two EMIs must not end up with two copies of Checkout in the page. The promise
 * is cached on `window` rather than in module scope so it survives a hot reload
 * during development, which otherwise re-injects on every edit.
 */

const SRC = 'https://checkout.razorpay.com/v1/checkout.js';
const CACHE = '__cashuRazorpayLoader';

function loadCheckout() {
  if (typeof window === 'undefined') return Promise.reject(new Error('No window.'));
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  if (window[CACHE]) return window[CACHE];

  window[CACHE] = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${SRC}"]`);
    const script = existing || document.createElement('script');

    script.addEventListener('load', () => {
      if (window.Razorpay) resolve(window.Razorpay);
      else reject(new Error('Checkout loaded but did not register.'));
    });

    script.addEventListener('error', () => {
      // Let a later attempt retry rather than caching the failure forever -
      // this is usually a flaky network or an ad blocker the user can disable.
      delete window[CACHE];
      reject(new Error('Could not load the payment gateway. Check your connection.'));
    });

    if (!existing) {
      script.src = SRC;
      script.async = true;
      document.body.appendChild(script);
    }
  });

  return window[CACHE];
}

export function useRazorpay() {
  const [ready, setReady] = useState(Boolean(window?.Razorpay));
  const [error, setError] = useState('');
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    loadCheckout()
      .then(() => mounted.current && setReady(true))
      .catch((err) => mounted.current && setError(err.message));

    return () => {
      mounted.current = false;
    };
  }, []);

  /**
   * Open Checkout and resolve with what happened.
   *
   * Resolves `{ outcome: 'paid', response }` when the handler fires,
   * `{ outcome: 'dismissed' }` when the user closes the sheet, and
   * `{ outcome: 'failed', error }` when Razorpay reports a failed attempt.
   *
   * Note what this does *not* do: decide that money moved. `paid` here means
   * only that Checkout called its success handler, and the caller must take
   * that to the server to be verified.
   *
   * `settled` guards against Razorpay firing both `handler` and `ondismiss`
   * for one session, which it does on some Android UPI returns - without it
   * the promise resolves twice and the second resolution is silently dropped
   * after the flow has already moved on.
   */
  const open = useCallback(async (options) => {
    const Checkout = await loadCheckout();

    return new Promise((resolve) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        resolve(result);
      };

      const instance = new Checkout({
        ...options,
        handler: (response) => finish({ outcome: 'paid', response }),
        modal: {
          ...(options.modal || {}),
          ondismiss: () => finish({ outcome: 'dismissed' }),
          // Keep the user in the sheet if they tap outside it mid-payment;
          // an accidental dismissal after authorising is how payments get
          // stranded.
          escape: false,
          backdropclose: false,
        },
      });

      instance.on('payment.failed', (event) => {
        finish({ outcome: 'failed', error: event?.error || {} });
      });

      instance.open();
    });
  }, []);

  return { ready, error, open };
}

export default useRazorpay;
