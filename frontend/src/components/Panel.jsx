export default function Panel({ title, subtitle, className = '', children }) {
  return (
    <section className={`rounded-2xl border border-line bg-canvas p-5 ${className}`}>
      {(title || subtitle) && (
        <header className="mb-4">
          {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
          {subtitle && <p className="mt-1 text-sm text-slate">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  );
}
