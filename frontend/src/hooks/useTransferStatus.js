import { useCallback, useEffect, useRef, useState } from 'react';

import { getTransfer, isTerminal } from '../api/transfers';

/**
 * Poll a transfer until it settles.
 *
 * Polling exists because the money path is asynchronous on both legs: the card
 * charge is confirmed by a Cashfree webhook, and the IMPS payout can sit in
 * PAYOUT_PROCESSING for a while - or fail and be retried three times before the
 * circuit breaker refunds the card. None of that reaches the browser on its
 * own, and a screen that stops updating while money is in flight is the one
 * thing guaranteed to make someone call support.
 *
 * Backs off as it goes: the interesting transitions happen in the first few
 * seconds, and a transfer still moving after two minutes is one the retry
 * ladder owns, not something worth hammering the API over.
 */

const INITIAL_INTERVAL = 2000;
const MAX_INTERVAL = 15000;
const BACKOFF = 1.4;

export default function useTransferStatus(transferId, { enabled = true } = {}) {
  const [transfer, setTransfer] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(transferId));

  const timerRef = useRef(null);
  const intervalRef = useRef(INITIAL_INTERVAL);
  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!transferId) return null;
    try {
      const next = await getTransfer(transferId);
      if (!cancelledRef.current) {
        setTransfer(next);
        setError(null);
      }
      return next;
    } catch (cause) {
      // Keep the last known state on screen. A dropped poll is not news, and
      // replacing a live transfer with an error would read as "it failed".
      if (!cancelledRef.current) setError(cause);
      return null;
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [transferId]);

  useEffect(() => {
    cancelledRef.current = false;
    intervalRef.current = INITIAL_INTERVAL;

    if (!transferId || !enabled) {
      setLoading(false);
      return undefined;
    }

    async function tick() {
      const next = await refresh();

      if (cancelledRef.current) return;

      if (next && isTerminal(next.status)) return;

      intervalRef.current = Math.min(intervalRef.current * BACKOFF, MAX_INTERVAL);
      timerRef.current = setTimeout(tick, intervalRef.current);
    }

    tick();

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [transferId, enabled, refresh]);

  return {
    transfer,
    error,
    loading,
    refresh,
    settled: transfer ? isTerminal(transfer.status) : false,
  };
}
