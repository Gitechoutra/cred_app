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
    <div className="space-y-6">
      {SECTIONS.map((section) => (
        <Section key={section.title} title={section.title} className="stagger-group">
          {/* Three across at 320px leaves room for a two-word label without
              truncating; four from `sm` up keeps the rows from stretching. */}
          <div className="stagger grid grid-cols-3 gap-2.5 sm:grid-cols-4">
            {section.items.map((item) => (
              <FeatureTile key={item.to} {...item} onClick={() => navigate(item.to)} />
            ))}
          </div>
        </Section>
      ))}

      {isAdmin && (
        <Section title="Operations">
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
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
        'group relative flex flex-col items-center gap-2 overflow-hidden rounded-2xl',
        'border border-line bg-canvas px-2 py-4 text-center',
        'transition-all duration-base ease-glide',
        'hover:-translate-y-1 hover:border-mint/40 hover:shadow-lift',
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
          'relative grid h-11 w-11 shrink-0 place-items-center rounded-xl',
          'bg-mint-50 text-mint-700 transition-all duration-base ease-glide',
          'group-hover:scale-110 group-hover:bg-mint group-hover:text-ink',
          'group-hover:shadow-mint group-active:scale-100',
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
