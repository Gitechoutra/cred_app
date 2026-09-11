import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints, tokens } from '../../api/client';
import { Logo } from '../../components/layout/AppShell';
import { Button, Input, cx } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import PinPad, { PinDots } from './PinPad';

const ADMIN_ROLES = ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'];

/**
 * Staff entrance to the operations console.
 *
 * Deliberately a different surface from the member login: dark, restrained, no
 * marketing. It reads as a back office because that is what it opens.
 *
 * A non-staff account that reaches here is signed straight back out and told
 * plainly which door it wants. Leaving a member half-authenticated on a screen
 * they cannot use is how people end up filing support tickets - and the
 * credentials are identical between doors, so this is an easy mistake to make.
 */
export default function AdminLogin() {
  const navigate = useNavigate();
  const { signIn, signOut } = useAuth();
  const { refresh } = useProfile();

  const [phone, setPhone] = useState('');
  const [pin, setPin] = useState('');
  const [stage, setStage] = useState('phone');
  const [error, setError] = useState('');
  const [wrongDoor, setWrongDoor] = useState(false);
  const [loading, setLoading] = useState(false);

  const phoneValid = /^[6-9]\d{9}$/.test(phone);

  function press(digit) {
    if (pin.length >= 6 || loading) return;

    const next = pin + digit;
    setPin(next);
    setError('');
    setWrongDoor(false);

    if (next.length === 6) submit(next);
  }

  async function submit(finalPin) {
    setLoading(true);

    try {
      const response = await endpoints.auth.loginMpin(phone, finalPin);
      const role = response.data?.user?.role;

      // Authenticate first, then check the role - the API does not expose a
      // "is this phone an admin" endpoint, and it should not: that would let
      // anyone enumerate which numbers hold staff accounts.
      if (!ADMIN_ROLES.includes(role)) {
        tokens.clear();
        setWrongDoor(true);
        setPin('');
        setLoading(false);
        return;
      }

      signIn(response.data);
      await refresh();
      navigate('/admin', { replace: true });
    } catch (err) {
      setError(err.message);
      setPin('');
      setLoading(false);
    }
  }

  /* ── Wrong door ──────────────────────────────────────────────────── */
  if (wrongDoor) {
    return (
      <Frame>
        <div className="text-center">
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-warn/15 text-warn">
            <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7.5v5.5M12 16.5h.01" strokeLinecap="round" />
            </svg>
          </div>

          <h1 className="mt-5 text-xl font-bold text-white">
            This is a member account
          </h1>
          <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-white/55">
            Your credentials are correct, but this account doesn&rsquo;t have
            staff access. Members sign in through the main entrance.
          </p>

          <div className="mt-7 space-y-2.5">
            <Button variant="mint" size="lg" full onClick={() => navigate('/signin/mpin')}>
              Go to user login
            </Button>
            <Button
              variant="ghost"
              size="lg"
              full
              className="text-white/60 hover:bg-white/5 hover:text-white"
              onClick={() => {
                setWrongDoor(false);
                setStage('phone');
                setPhone('');
              }}
            >
              Try a different account
            </Button>
          </div>

          <p className="mt-6 text-2xs leading-relaxed text-white/35">
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
      <Frame>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (phoneValid) setStage('pin');
          }}
        >
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-2xs font-semibold text-mint">
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            Staff access only
          </span>

          <h1 className="mt-5 text-2xl font-bold tracking-tight text-white">
            Operations console
          </h1>
          <p className="mt-2 text-sm text-white/50">
            Sign in with your CashU staff account.
          </p>

          <div className="mt-8">
            <label htmlFor="admin-phone" className="mb-1.5 block text-sm font-medium text-white/80">
              Registered mobile number
            </label>
            <div className="flex h-12 items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-3.5 transition focus-within:border-mint/40 focus-within:ring-2 focus-within:ring-mint/20">
              <span className="shrink-0 text-sm font-medium text-white/60">+91</span>
              <input
                id="admin-phone"
                inputMode="numeric"
                autoComplete="tel-national"
                autoFocus
                placeholder="98765 43210"
                value={phone}
                maxLength={10}
                onChange={(event) => setPhone(event.target.value.replace(/\D/g, '').slice(0, 10))}
                className="money w-full bg-transparent text-[15px] text-white outline-none placeholder:text-white/25"
              />
            </div>
          </div>

          <Button
            type="submit"
            variant="mint"
            size="lg"
            full
            className="mt-6"
            disabled={!phoneValid}
          >
            Continue
          </Button>

          <div className="mt-7 border-t border-white/10 pt-5 text-center">
            <p className="text-2xs text-white/40">Not staff?</p>
            <button
              type="button"
              onClick={() => navigate('/signin')}
              className="mt-1 text-sm font-semibold text-mint hover:underline"
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
    <Frame wide>
      <div className="flex flex-col items-center text-center">
        <h1 className="text-xl font-bold tracking-tight text-white">
          Enter your MPIN
        </h1>
        <p className="money mt-1.5 text-sm text-white/50">+91 {phone}</p>

        <PinDots length={6} filled={pin.length} error={Boolean(error)} className="mt-8" />

        {error && <p className="mt-4 max-w-xs text-sm text-alert">{error}</p>}
      </div>

      <div className="mt-8 [&_button]:text-white [&_button:active]:bg-white/10">
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
        className="mt-1 w-full text-center text-sm font-medium text-white/50 transition hover:text-white"
      >
        Use a different number
      </button>
    </Frame>
  );
}

/* ── Frame ──────────────────────────────────────────────────────────────── */

/**
 * The ink canvas that makes this feel like a back office rather than the
 * customer app, which is white throughout.
 */
function Frame({ children, wide = false }) {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col bg-ink">
      <header className="border-b border-white/10">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex flex-1 items-center gap-2.5 text-left"
          >
            <Logo className="h-8 w-8" />
            <div>
              <p className="text-base font-bold leading-none text-white">CashU</p>
              <p className="mt-0.5 text-2xs text-mint">Operations</p>
            </div>
          </button>

          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded-xl px-3 py-2 text-xs font-medium text-white/50 transition hover:bg-white/5 hover:text-white"
          >
            Back to site
          </button>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className={cx('w-full', wide ? 'max-w-xs' : 'max-w-sm')}>{children}</div>
      </main>

      <footer className="px-4 pb-8 text-center">
        <p className="mx-auto max-w-sm text-2xs leading-relaxed text-white/30">
          Access to this console is logged. Viewing customer personal data and
          reversing transactions are recorded against your account.
        </p>
      </footer>
    </div>
  );
}
