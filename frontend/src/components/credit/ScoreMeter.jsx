/**
 * A half-circle credit score gauge, 300-900, coloured by band.
 *
 * Bands match the backend's score_band(): below 650 poor, 650 fair, 700 good,
 * 750 very good, 800 excellent.
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

export function scoreColor(score) {
  if (score == null) return '#94A3A0';
  const band = SCORE_BANDS.find((b) => score >= b.from && score < b.to);
  return (band || SCORE_BANDS[SCORE_BANDS.length - 1]).color;
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
        aria-label={has ? `Credit score ${score} out of ${MAX}` : 'No credit score'}
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
          {has ? score : '—'}
        </text>
        <text x="100" y="112" textAnchor="middle"
          style={{ fontSize: 11, fontWeight: 600 }} fill={scoreColor(score)}
        >
          {band || (has ? '' : 'Not checked')}
        </text>
        <text x="16" y="116" textAnchor="middle" fill="#94A3A0" style={{ fontSize: 9 }}>{MIN}</text>
        <text x="184" y="116" textAnchor="middle" fill="#94A3A0" style={{ fontSize: 9 }}>{MAX}</text>
      </svg>
    </div>
  );
}
