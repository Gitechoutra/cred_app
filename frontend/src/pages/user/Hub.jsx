import { useNavigate } from 'react-router-dom';

import {
  IconBank,
  IconCard,
  IconChart,
  IconEmi,
  IconHelp,
  IconLock,
  IconReceipt,
  IconShield,
  IconTransfer,
  IconUser,
} from '../../components/layout/AppShell';
import { Section, cx } from '../../components/ui';
import { useProfile } from '../../hooks/useProfile';

/**
 * The feature hub - the first screen after signing in.
 *
 * It answers "what can I do here?" rather than "how much do you owe?". The
 * dashboard still exists, unchanged, one tap away; it is simply no longer the
 * thing that greets someone the moment they open the app.
 *
 * Deliberately static. This screen makes no API calls, which is the point:
 * nothing here can surface an outstanding balance, a missed installment or a
 * utilisation warning. It is also why it renders instantly instead of behind
 * three skeletons.
 *
 * Every tile points at a route that already exists. Nothing was invented to
 * fill the grid.
 */

const SECTIONS = [
  {
    title: 'Payments',
    items: [
      { to: '/transfer', label: 'Transfer', hint: 'Card to bank', icon: IconTransfer },
      { to: '/emi', label: 'EMIs', hint: 'Pay installments', icon: IconEmi },
    ],
  },
  {
    title: 'Your money',
    items: [
      { to: '/dashboard', label: 'Dashboard', hint: 'Full overview', icon: IconChart },
      { to: '/cards', label: 'Cards', hint: 'Linked cards', icon: IconCard },
      { to: '/banks', label: 'Bank accounts', hint: 'Payout accounts', icon: IconBank },
      { to: '/transactions', label: 'History', hint: 'All activity', icon: IconReceipt },
    ],
  },
  {
    title: 'Account',
    items: [
      { to: '/profile', label: 'Profile', hint: 'Your details', icon: IconUser },
      { to: '/kyc', label: 'KYC', hint: 'Verification', icon: IconShield },
      { to: '/security', label: 'Security', hint: 'MPIN & devices', icon: IconLock },
      { to: '/support', label: 'Help', hint: 'Get support', icon: IconHelp },
    ],
  },
];

export default function Hub() {
  const navigate = useNavigate();
  const { isAdmin } = useProfile();

  return (
    // Capped narrower than the shell's max-w-6xl. At full width four columns
    // stretch each tile to roughly 280x130 - a letterbox that reads as a toolbar
    // rather than a considered grid. Holding the grid to ~900px keeps the tiles
    // close to square, which is what makes the page feel composed.
    <div className="mx-auto w-full max-w-4xl space-y-8">
      {SECTIONS.map((section) => (
        <Section key={section.title} title={section.title} className="stagger-group">
          {/* Three across at 320px leaves room for a two-word label without
              truncating; four from `sm` up keeps the rows from stretching. */}
          <div className="stagger grid grid-cols-3 gap-3 sm:grid-cols-4">
            {section.items.map((item) => (
              <FeatureTile key={item.to} {...item} onClick={() => navigate(item.to)} />
            ))}
          </div>
        </Section>
      ))}

      {isAdmin && (
        <Section title="Operations" className="stagger-group">
          <div className="stagger grid grid-cols-3 gap-3 sm:grid-cols-4">
            <FeatureTile
              to="/admin"
              label="Console"
              hint="Admin tools"
              icon={IconLock}
              onClick={() => navigate('/admin')}
            />
          </div>
        </Section>
      )}
    </div>
  );
}

function FeatureTile({ label, hint, icon: Icon, onClick, className }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        // No `shine` here: that sweep is a white gradient, which is invisible on
        // a white tile. It earns its place on CardTile, which has a brand colour
        // behind it.
        'group relative flex min-h-[124px] flex-col items-center justify-center',
        'gap-2.5 overflow-hidden rounded-2xl',
        // shadow-card at rest, not just a hairline border. A flat bordered
        // rectangle reads as a form field; a tile that already sits above the
        // page has somewhere to rise to on hover.
        'border border-line bg-canvas px-3 py-6 text-center shadow-card',
        'transition-all duration-base ease-glide',
        'hover:-translate-y-1 hover:border-mint-600/40 hover:shadow-lift',
        'active:translate-y-0 active:scale-[0.96] active:duration-micro',
        className,
      )}
    >
      {/* A mint wash growing from the centre on hover. Behind the content and
          pointer-events-none, so it tints without intercepting the click. */}
      <span
        aria-hidden="true"
        className={cx(
          'pointer-events-none absolute inset-0 scale-90 rounded-2xl bg-mint-50/70',
          'opacity-0 transition-all duration-base ease-glide',
          'group-hover:scale-100 group-hover:opacity-100',
        )}
      />

      <span
        className={cx(
          'relative grid h-12 w-12 shrink-0 place-items-center rounded-2xl',
          // A hairline ring inside the chip catches the light the way a pressed
          // edge would, so the mint square has an edge rather than sitting flat.
          'bg-mint-50 text-mint-700 ring-1 ring-inset ring-mint-600/10',
          'transition-all duration-base ease-glide',
          'group-hover:scale-110 group-hover:bg-mint group-hover:text-ink',
          'group-hover:shadow-mint group-hover:ring-transparent group-active:scale-100',
        )}
      >
        <Icon className="h-[22px] w-[22px]" />
      </span>

      <span className="relative min-w-0">
        <span className="block truncate text-xs font-semibold text-ink">{label}</span>
        <span
          className={cx(
            'mt-0.5 block truncate text-2xs text-slate',
            'transition-colors duration-base group-hover:text-mint-800',
          )}
        >
          {hint}
        </span>
      </span>
    </button>
  );
}
