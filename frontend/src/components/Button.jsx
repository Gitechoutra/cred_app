/**
 * Mint is punctuation, so exactly one primary action is visible per screen.
 * Text on a mint fill is always ink - mint on white fails WCAG AA below 18px.
 */
export default function Button({
  variant = 'primary',
  loading = false,
  disabled = false,
  className = '',
  children,
  ...props
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 ' +
    'text-sm font-semibold transition disabled:cursor-not-allowed';

  const variants = {
    primary: 'bg-mint text-ink hover:brightness-95 disabled:bg-mist disabled:text-slate',
    secondary: 'bg-ink text-white hover:bg-ink/90 disabled:bg-mist disabled:text-slate',
    ghost: 'bg-transparent text-ink hover:bg-mist disabled:text-slate',
    danger: 'bg-alert text-white hover:brightness-95 disabled:bg-mist disabled:text-slate',
  };

  return (
    <button
      className={`${base} ${variants[variant]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <span
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
}
