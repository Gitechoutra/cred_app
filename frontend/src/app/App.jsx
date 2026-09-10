import { Link } from 'react-router-dom';

import AppRoutes from './routes';

export default function App() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link to="/" className="flex items-center gap-2">
            <Logo />
            <span className="text-lg font-semibold tracking-tight text-ink">CashU</span>
          </Link>
        </div>
      </header>

      <main>
        <AppRoutes />
      </main>
    </div>
  );
}

/**
 * "The Coin Cut" (version1.md 3.3) — a U drawn as the lower arc of a coin, its
 * negative space cutting an upward notch: currency and headroom at once.
 */
function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill="#00F5B8" />
      <path
        d="M10 10v7a6 6 0 0 0 12 0v-7"
        fill="none"
        stroke="#0A0F0D"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
