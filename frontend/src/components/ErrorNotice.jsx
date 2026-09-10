/**
 * Renders an ApiError.
 *
 * The backend's `message` is the exact PRD section 20 user-facing string and
 * `recovery` is the suggested next action from the same table, so both are
 * shown as sent rather than reworded here.
 */
export default function ErrorNotice({ error, className = '' }) {
  if (!error) return null;

  return (
    <div
      role="alert"
      className={`rounded-xl border border-alert/30 bg-canvas p-4 ${className}`}
    >
      <p className="text-sm font-medium text-alert">{error.message}</p>
      {error.recovery && <p className="mt-1 text-sm text-slate">{error.recovery}</p>}
      {error.code && (
        <p className="mt-2 text-xs text-slate">Reference: {error.code}</p>
      )}
    </div>
  );
}
