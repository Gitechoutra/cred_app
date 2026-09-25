import { useCallback, useEffect, useState } from 'react';

/**
 * Form state that survives leaving the screen and coming back.
 *
 * Going back to check a balance and returning should not mean typing an
 * application out again. Kept in sessionStorage - this tab only, gone when it
 * closes - and cleared by the caller once the form is submitted, so a finished
 * form never reappears pre-filled.
 *
 * Never used for anything secret. Nothing sensitive is ever entered into these
 * forms: there is no card number, CVV, PIN or OTP anywhere in the credit flow.
 */
export function useSessionDraft(key, initial) {
  const storageKey = `cashu.draft.${key}`;

  const [value, setValue] = useState(() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey));
      return stored && typeof stored === 'object' ? { ...initial, ...stored } : initial;
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      /* Private browsing: the draft simply does not persist. */
    }
  }, [storageKey, value]);

  const update = useCallback((patch) => {
    setValue((current) => ({ ...current, ...patch }));
  }, []);

  const clear = useCallback(() => {
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
    setValue(initial);
    // `initial` is a literal at every call site; depending on it would reset
    // the draft on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  return [value, update, clear];
}

export default useSessionDraft;
