import { createContext, useCallback, useContext, useMemo, useState } from 'react';

const ToastContext = createContext(null);

let nextId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (message, { tone = 'neutral', duration = 4000, action } = {}) => {
      const id = ++nextId;
      setToasts((current) => [...current, { id, message, tone, action }]);

      if (duration) {
        setTimeout(() => dismiss(id), duration);
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({
      push,
      dismiss,
      success: (message, options) => push(message, { ...options, tone: 'good' }),
      error: (message, options) =>
        // Errors linger: a failure the user did not read is a support ticket.
        push(message, { duration: 6000, ...options, tone: 'alert' }),
      info: (message, options) => push(message, { ...options, tone: 'neutral' }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

function ToastViewport({ toasts, onDismiss }) {
  if (!toasts.length) return null;

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-[100] flex flex-col items-center gap-2 px-4 pb-24 pointer-events-none sm:pb-6"
      role="region"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={[
            'pointer-events-auto w-full max-w-sm animate-fade-up rounded-2xl px-4 py-3',
            'shadow-lift flex items-start gap-3 text-sm',
            toast.tone === 'good' && 'bg-ink text-white',
            toast.tone === 'alert' && 'bg-alert text-white',
            toast.tone === 'neutral' && 'bg-ink text-white',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {toast.tone === 'good' && (
            <span
              className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-mint text-ink"
              aria-hidden="true"
            >
              <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none">
                <path
                  d="M5 10.5l3.5 3.5L15 7"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          )}

          <p className="flex-1 leading-snug">{toast.message}</p>

          {toast.action ? (
            <button
              type="button"
              onClick={() => {
                toast.action.onClick();
                onDismiss(toast.id);
              }}
              className="shrink-0 font-semibold text-mint"
            >
              {toast.action.label}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss"
              className="shrink-0 opacity-60 transition hover:opacity-100"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
                <path
                  d="M5 5l10 10M15 5L5 15"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used inside a ToastProvider.');
  }
  return context;
}
