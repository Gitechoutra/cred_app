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
        <Section key={section.title} title={section.title}>
          {/* Three across at 320px leaves room for a two-word label without
              truncating; four from `sm` up keeps the rows from stretching. */}
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
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
        'flex flex-col items-center gap-2 rounded-2xl border border-line bg-canvas',
        'px-2 py-4 text-center transition',
        'hover:border-ink/20 hover:shadow-card active:scale-[0.98]',
        className,
      )}
    >
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-mint-50 text-mint-700">
        <Icon className="h-[22px] w-[22px]" />
      </span>

      <span className="min-w-0">
        <span className="block truncate text-xs font-semibold text-ink">{label}</span>
        <span className="mt-0.5 block truncate text-2xs text-slate">{hint}</span>
      </span>
    </button>
  );
}
