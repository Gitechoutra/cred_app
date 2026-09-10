import { cx } from '../../components/ui';

/**
 * Numeric keypad.
 *
 * A custom pad rather than a native numeric input: it keeps the digits off the
 * system keyboard's autocomplete, and it lets the layout stay fixed so muscle
 * memory works - which is the whole point of a PIN.
 */
export default function PinPad({ onPress, onBackspace, disabled }) {
  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'back'];

  return (
    <div className="grid grid-cols-3 gap-2 pb-4">
      {keys.map((key, index) => {
        if (key === '') return <span key={index} />;

        if (key === 'back') {
          return (
            <button
              key={index}
              type="button"
              onClick={onBackspace}
              disabled={disabled}
              aria-label="Delete"
              className="grid h-16 place-items-center rounded-2xl text-ink transition active:scale-95 active:bg-mist disabled:opacity-40"
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
            className="money grid h-16 place-items-center rounded-2xl text-2xl font-medium text-ink transition active:scale-95 active:bg-mist disabled:opacity-40"
          >
            {key}
          </button>
        );
      })}
    </div>
  );
}

export function PinDots({ length = 6, filled = 0, error = false, className }) {
  return (
    <div className={cx('flex items-center gap-3', className)} aria-hidden="true">
      {Array.from({ length }, (_, index) => (
        <span
          key={index}
          className={cx(
            'h-3.5 w-3.5 rounded-full transition-all duration-200',
            error
              ? 'bg-alert'
              : index < filled
                ? 'scale-110 bg-ink'
                : 'bg-line',
          )}
        />
      ))}
    </div>
  );
}
