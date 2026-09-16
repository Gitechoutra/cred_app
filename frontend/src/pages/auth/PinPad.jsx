import { useEffect } from 'react';

import { cx } from '../../components/ui';

/**
 * Numeric keypad.
 *
 * A custom pad rather than a native numeric input: it keeps the digits out of
 * the browser's autofill and form history, and it lets the layout stay fixed so
 * muscle memory works — which is the whole point of a PIN.
 *
 * Because it is not a real input, a physical keyboard would do nothing without
 * the listener below. On a desktop browser most people type rather than click,
 * so the pad binds the number row, the numpad and Backspace to the same
 * handlers the on-screen keys use.
 *
 * `tone` exists because this renders on two very different surfaces: the white
 * member app and the ink-dark operations console. Without it the filled dots
 * are drawn in ink on an ink background and simply disappear as you type.
 */
export default function PinPad({ onPress, onBackspace, disabled, tone = 'light' }) {
  useEffect(() => {
    if (disabled) return undefined;

    const onKeyDown = (event) => {
      // Never steal keystrokes from a real field — a phone input, a search box
      // or anything else focused elsewhere on the page.
      const target = event.target;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) {
        return;
      }

      // Leave browser and OS shortcuts alone.
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key >= '0' && event.key <= '9') {
        event.preventDefault();
        onPress?.(event.key);
        return;
      }

      if (event.key === 'Backspace' || event.key === 'Delete') {
        // Backspace navigates back in some browsers when nothing is focused.
        event.preventDefault();
        onBackspace?.();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onPress, onBackspace, disabled]);

  const dark = tone === 'dark';
  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'back'];

  const keyClass = cx(
    'grid h-16 place-items-center rounded-2xl transition active:scale-95 disabled:opacity-40',
    dark ? 'text-white active:bg-white/10' : 'text-ink active:bg-mist',
  );

  return (
    <div className="pb-4">
      <div className="grid grid-cols-3 gap-2" role="group" aria-label="PIN keypad">
        {keys.map((key, index) => {
          if (key === '') return <span key={index} />;

          if (key === 'back') {
            return (
              <button
                key={index}
                type="button"
                onClick={onBackspace}
                disabled={disabled}
                aria-label="Delete last digit"
                className={keyClass}
              >
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none">
                  <path
                    d="M9 5h11v14H9l-6-7z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M12 10l4 4M16 10l-4 4"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            );
          }

          return (
            <button
              key={index}
              type="button"
              onClick={() => onPress(key)}
              disabled={disabled}
              className={cx(keyClass, 'money text-2xl font-medium')}
            >
              {key}
            </button>
          );
        })}
      </div>

      {/* Desktop affordance — the pad is clickable, but typing is faster and
          nothing else suggests it works. */}
      <p
        className={cx(
          'mt-3 hidden text-center text-2xs sm:block',
          dark ? 'text-white/35' : 'text-slate',
        )}
      >
        You can also type on your keyboard
      </p>
    </div>
  );
}

export function PinDots({ length = 6, filled = 0, error = false, className, tone = 'light' }) {
  const dark = tone === 'dark';

  return (
    <div
      className={cx('flex items-center gap-3', className)}
      role="status"
      aria-label={`${filled} of ${length} digits entered`}
    >
      {Array.from({ length }, (_, index) => {
        const isFilled = index < filled;

        return (
          <span
            key={index}
            className={cx(
              'h-3.5 w-3.5 rounded-full transition-all duration-200',
              error
                ? 'bg-alert'
                : isFilled
                  ? cx('scale-110', dark ? 'bg-mint' : 'bg-ink')
                  : dark
                    ? 'bg-white/15'
                    : 'bg-line',
            )}
          />
        );
      })}
    </div>
  );
}
