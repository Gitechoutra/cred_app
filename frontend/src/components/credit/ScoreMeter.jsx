/**
 * A half-circle credit score gauge, 300-900.
 *
 * Draws what the backend returned and nothing else: the score, and the band
 * label from the backend's score_band(). The arc segments are only the scale's
 * decoration; the band shown is never worked out here. With no score - new to
 * credit, or not fetched - it reads "N/A" and the status the backend gave.
 */

const MIN = 300;
const MAX = 900;

export const SCORE_BANDS = [
  { from: 300, to: 650, color: '#EF4444' },
  { from: 650, to: 700, color: '#F59E0B' },
  { from: 700, to: 750, color: '#A3D94A' },
  { from: 750, to: 800, color: '#00C594' },
  { from: 800, to: 900, color: '#009170' },
];

// Keyed by the backend's band label, so a colour can never disagree with it.
const BAND_COLORS = {
  Poor: '#EF4444',
  Fair: '#F59E0B',
  Good: '#A3D94A',
  'Very good': '#00C594',
  Excellent: '#009170',
};

// The backend's bureau codes, for display. A score is always shown with the
// bureau that produced it: each bureau scores the same person differently.
const BUREAU_LABELS = {
  EXPERIAN: 'Experian',
  CRIF: 'CRIF High Mark',
  EQUIFAX: 'Equifax',
  CIBIL: 'TransUnion CIBIL',
  SANDBOX: 'CashU sandbox',
};

export function bureauLabel(bureau) {
  return BUREAU_LABELS[bureau] || 'the credit bureau';
}

export function bandColor(band) {
  return BAND_COLORS[band] || '#94A3A0';
}

// Angle along the arc, 180deg (left, 300) to 0deg (right, 900).
function point(value, radius, cx = 100, cy = 100) {
  const t = (Math.min(MAX, Math.max(MIN, value)) - MIN) / (MAX - MIN);
  const angle = Math.PI * (1 - t);
  return [cx + radius * Math.cos(angle), cy - radius * Math.sin(angle)];
}

function arc(from, to, radius) {
  const [x1, y1] = point(from, radius);
  const [x2, y2] = point(to, radius);
  return `M ${x1} ${y1} A ${radius} ${radius} 0 0 1 ${x2} ${y2}`;
}

export default function ScoreMeter({ score, band, size = 'md' }) {
  const width = size === 'sm' ? 160 : 240;
  const has = score != null;
  const [mx, my] = point(has ? score : MIN, 80);

  return (
    <div className="mx-auto" style={{ width }}>
      <svg viewBox="0 0 200 118" className="w-full" role="img"
        aria-label={has ? `Credit score ${score} out of ${MAX}` : 'Credit score not available'}
      >
        {SCORE_BANDS.map((b) => (
          <path key={b.from} d={arc(b.from + 1, b.to - 1, 80)} fill="none"
            stroke={b.color} strokeWidth="14" strokeLinecap="butt"
            opacity={has ? 0.9 : 0.25}
          />
        ))}
        {has && (
          <circle cx={mx} cy={my} r="9" fill="#fff" stroke="#0A0F0D" strokeWidth="3" />
        )}
        <text x="100" y="92" textAnchor="middle" className="fill-ink"
          style={{ fontSize: 34, fontWeight: 700 }}
        >
          {has ? score : 'N/A'}
        </text>
        <text x="100" y="112" textAnchor="middle"
          style={{ fontSize: 11, fontWeight: 600 }} fill={bandColor(band)}
        >
          {band || (has ? '' : 'Not checked')}
        </text>
        <text x="16" y="116" textAnchor="middle" fill="#94A3A0" style={{ fontSize: 9 }}>{MIN}</text>
        <text x="184" y="116" textAnchor="middle" fill="#94A3A0" style={{ fontSize: 9 }}>{MAX}</text>
      </svg>
    </div>
  );
}
