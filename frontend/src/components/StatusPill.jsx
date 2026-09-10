import { statusLabel, statusTone } from '../utils/status';

const TONES = {
  mint: 'bg-mint text-ink',
  warn: 'bg-warn/10 text-warn',
  // Overdue and failed states use alert on a white ground, never a red fill -
  // this is a debt app, and a wall of red is hostile.
  alert: 'bg-canvas text-alert ring-1 ring-alert/30',
  slate: 'bg-mist text-slate',
};

export default function StatusPill({ status, className = '' }) {
  const tone = TONES[statusTone(status)] || TONES.slate;
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${tone} ${className}`}
    >
      {statusLabel(status)}
    </span>
  );
}
