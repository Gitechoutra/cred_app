import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Logo } from '../../components/layout/AppShell';
import { Button, cx } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import PinPad, { PinDots } from './PinPad';

/**
 * The two staff portals: what each is called, where it leads, and the accent
 * that tells them apart. Same white canvas and layout as the member app; the
 * badge colour, heading and label carry the difference.
 */
export const STAFF_PORTALS = {
  ADMIN: {
    badge: 'Admin access only',
    badgeClass: 'border-ink/15 bg-ink text-white',
    title: 'Operations console',
    subtitle: 'Sign in with your CashU administrator account.',
    label: 'Operations',
    labelClass: 'text-ink',
    home: '/admin',
    login: '/admin/login',
  },
  SUPPORT: {
    badge: 'Support agents only',
    badgeClass: 'border-sky-200 bg-sky-50 text-sky-800',
    title: 'Customer support desk',
    subtitle: 'Sign in with your CashU support agent account.',
    label: 'Support desk',
    labelClass: 'text-sky-700',
    home: '/support-desk',
    login: '/support-desk/login',
  },
};

/** Where each portal's sign-in lives, for "use the right door" links. */
const PORTAL_LOGIN = {
  USER: { path: '/signin/mpin', name: 'customer' },
  ADMIN: { path: '/admin/login', name: 'admin' },
  SUPPORT: { path: '/support-desk/login', name: 'support' },
};

export default function AdminLogin() {
  return <StaffLogin portal="ADMIN" />;
}

/**
 * Staff entrance, for the admin console or the support desk.
 *
 * The server checks the portal: an account from a different portal is refused
 * once its MPIN is proven, with no session opened, and told which door it
 * wants. Nothing here decides access from the role on the client.
 */
export function StaffLogin({ portal }) {
  const config = STAFF_PORTALS[portal];
  const navigate = useNavigate();
  const { signIn, signOut } = useAuth();
  const { refresh } = useProfile();

  const [phone, setPhone] = useState('');
  const [pin, setPin] = useState('');
  const [stage, setStage] = useState('phone');
  const [error, setError] = useState('');
  // The portal this account belongs to, after the server refuses this one.
  const [wrongDoor, setWrongDoor] = useState(null);
  const [loading, setLoading] = useState(false);

  const phoneValid = /^[6-9]\d{9}$/.test(phone);

  function press(digit) {
    if (pin.length >= 6 || loading) return;

    const next = pin + digit;
    setPin(next);
    setError('');
    setWrongDoor(null);

    if (next.length === 6) submit(next);
  }

  async function submit(finalPin) {
    setLoading(true);

    try {
      const response = await endpoints.auth.loginMpin(phone, finalPin, portal);
      signIn(response.data);
      await refresh();
      navigate(config.home, { replace: true });
    } catch (err) {
      if (err.code === 'WRONG_PORTAL') {
        setWrongDoor(err.details?.portal || 'USER');
        setPin('');
        setLoading(false);
        return;
      }
      setError(err.message);
      setPin('');
      setLoading(false);
    }
  }

  /* ── Wrong door ──────────────────────────────────────────────────── */
  if (wrongDoor) {
    const right = PORTAL_LOGIN[wrongDoor] || PORTAL_LOGIN.USER;
    return (
      <Frame config={config}>
        <div className="animate-rise-in rounded-2xl border border-line bg-canvas p-7 text-center shadow-card">
          <div className="mx-auto grid h-14 w-14 animate-scale-in place-items-center rounded-2xl bg-warn/15 text-warn">
            <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7.5v5.5M12 16.5h.01" strokeLinecap="round" />
            </svg>
          </div>

          <h1 className="mt-5 text-xl font-bold text-ink">
            {wrongDoor === 'USER' ? 'This is a member account' : 'Wrong sign-in for this account'}
          </h1>
          <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-slate">
            Your MPIN is correct, but this account signs in through the{' '}
            {right.name} login. Nothing was opened here.
          </p>

          <div className="mt-7 space-y-2.5">
            <Button variant="mint" size="lg" full onClick={() => navigate(right.path)}>
              Go to {right.name} login
            </Button>
            <Button
              variant="ghost"
              size="lg"
              full
              onClick={() => {
                setWrongDoor(null);
                setStage('phone');
                setPhone('');
              }}
            >
              Try a different account
            </Button>
          </div>

          <p className="mt-6 text-2xs leading-relaxed text-slate-light">
            Staff accounts are created by a CashU administrator. If you should
            have one, ask your team lead.
          </p>
        </div>
      </Frame>
    );
  }

  /* ── Phone ───────────────────────────────────────────────────────── */
  if (stage === 'phone') {
    return (
      <Frame config={config}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (phoneValid) setStage('pin');
          }}
        >
          {/* A contained panel rather than content floating on the page — it
              gives the form an edge to sit against and reads as a console
              sign-in. On white that edge is a hairline plus a soft shadow. */}
          <div className="animate-rise-in rounded-2xl border border-line bg-canvas p-7 shadow-card">
            <span
              className={cx(
                'inline-flex animate-fade-up items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs font-semibold',
                config.badgeClass,
              )}
            >
              <svg
                viewBox="0 0 24 24"
                className="h-3 w-3"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
                <path d="M8 10V7a4 4 0 0 1 8 0v3" />
              </svg>
              {config.badge}
            </span>

            <h1
              className="mt-5 animate-fade-up text-[1.75rem] font-bold leading-tight tracking-tight text-ink"
              style={{ animationDelay: '60ms' }}
            >
              {config.title}
            </h1>
            <p
              className="mt-1.5 animate-fade-up text-sm leading-relaxed text-slate"
              style={{ animationDelay: '110ms' }}
            >
              {config.subtitle}
            </p>

            <div className="mt-7 animate-fade-up" style={{ animationDelay: '160ms' }}>
              <label
                htmlFor="staff-phone"
                className="mb-2 block text-2xs font-semibold uppercase tracking-[0.12em] text-slate"
              >
                Registered mobile number
              </label>

              <div className="group flex h-14 items-center rounded-xl border border-line bg-mist transition-colors duration-200 focus-within:border-mint-600/50 focus-within:bg-canvas">
                <span className="money flex h-full shrink-0 items-center border-r border-line px-4 text-sm font-semibold text-slate transition-colors group-focus-within:text-mint-700">
                  +91
                </span>
                <input
                  id="staff-phone"
                  inputMode="numeric"
                  autoComplete="tel-national"
                  autoFocus
                  placeholder="98765 43210"
                  value={phone}
                  maxLength={10}
                  onChange={(event) =>
                    setPhone(event.target.value.replace(/\D/g, '').slice(0, 10))
                  }
                  className="money h-full w-full bg-transparent px-4 text-base tracking-wide text-ink outline-none ring-0 placeholder:font-normal placeholder:tracking-normal placeholder:text-slate-light focus:outline-none focus:ring-0"
                />

                {/* Quiet completion tick, so the field confirms itself. It pops
                    in rather than appearing, which is the only motion on this
                    screen tied to something the user just did. */}
                {phoneValid && (
                  <span className="mr-4 grid h-5 w-5 shrink-0 animate-pop place-items-center rounded-full bg-mint text-ink">
                    <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none">
                      <path
                        d="M5 10.5l3.5 3.5L15 7"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                )}
              </div>
            </div>

            <div className="animate-fade-up" style={{ animationDelay: '210ms' }}>
              <Button
                type="submit"
                variant="mint"
                size="lg"
                full
                className="group mt-5"
                disabled={!phoneValid}
              >
                Continue
                <svg
                  viewBox="0 0 20 20"
                  className="h-4 w-4 transition-transform duration-base ease-glide group-hover:translate-x-0.5"
                  fill="none"
                >
                  <path
                    d="M4 10h11M11 5l5 5-5 5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </Button>
            </div>
          </div>

          <div className="mt-6 animate-fade-up text-center" style={{ animationDelay: '260ms' }}>
            <p className="text-2xs text-slate-light">Not staff?</p>
            <button
              type="button"
              onClick={() => navigate('/signin')}
              className="mt-1 rounded-lg px-2 py-1 text-sm font-semibold text-mint-700 transition-colors duration-base ease-glide hover:bg-mint-50"
            >
              Go to user login
            </button>
          </div>
        </form>
      </Frame>
    );
  }

  /* ── MPIN ────────────────────────────────────────────────────────── */
  return (
    <Frame wide config={config}>
      <div className="flex animate-fade-up flex-col items-center text-center">
        <h1 className="text-xl font-bold tracking-tight text-ink">
          Enter your MPIN
        </h1>
        <p className="money mt-1.5 text-sm text-slate">+91 {phone}</p>

        <PinDots
          length={6}
          filled={pin.length}
          error={Boolean(error)}
          className="mt-8"
        />

        {error && (
          <p className="mt-4 max-w-xs animate-slide-down text-sm text-alert">{error}</p>
        )}
      </div>

      <div className="mt-8 animate-fade-up" style={{ animationDelay: '80ms' }}>
        <PinPad
          onPress={press}
          onBackspace={() => {
            setPin(pin.slice(0, -1));
            setError('');
          }}
          disabled={loading}
        />
      </div>

      <button
        type="button"
        onClick={() => {
          setStage('phone');
          setPin('');
          setError('');
        }}
        className="mt-1 w-full text-center text-sm font-medium text-slate transition-colors duration-base ease-glide hover:text-ink"
      >
        Use a different number
      </button>
      <button
        type="button"
        onClick={() => navigate(`/forgot-mpin?portal=${portal}&phone=${phone}`)}
        className="mt-1 w-full text-center text-sm font-semibold text-mint-700 transition-colors duration-base ease-glide hover:text-mint-800"
      >
        Forgot MPIN?
      </button>
    </Frame>
  );
}

/* ── Frame ──────────────────────────────────────────────────────────────── */

/**
 * The shell shared by every stage of the console sign-in.
 *
 * White, like the member app. What marks this as staff territory is the
 * "Operations" label under the mark and the logging notice at the foot, not a
 * different colour scheme.
 */
function Frame({ children, wide = false, config = STAFF_PORTALS.ADMIN }) {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="border-b border-line">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="group flex flex-1 items-center gap-2.5 text-left"
          >
            <Logo className="h-8 w-8 transition-transform duration-base ease-glide group-hover:scale-105" />
            <div>
              <p className="text-base font-bold leading-none text-ink">CashU</p>
              <p className={cx('mt-0.5 text-2xs font-semibold', config.labelClass)}>{config.label}</p>
            </div>
          </button>

          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded-xl px-3 py-2 text-xs font-medium text-slate transition-colors duration-base ease-glide hover:bg-mist hover:text-ink"
          >
            Back to site
          </button>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className={cx('w-full', wide ? 'max-w-xs' : 'max-w-sm')}>{children}</div>
      </main>

      <footer className="px-4 pb-8 text-center">
        <p className="mx-auto max-w-sm text-2xs leading-relaxed text-slate-light">
          Access to this console is logged. Viewing customer personal data and
          reversing transactions are recorded against your account.
        </p>
      </footer>
    </div>
  );
}
