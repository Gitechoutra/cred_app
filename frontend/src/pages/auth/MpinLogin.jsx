import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Button, Input } from '../../components/ui';
import { PageHeader } from '../../components/layout/AppShell';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import PinPad, { PinDots } from './PinPad';

export default function MpinLogin() {
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const { refresh } = useProfile();

  const [phone, setPhone] = useState('');
  const [pin, setPin] = useState('');
  const [stage, setStage] = useState('phone');
  const [error, setError] = useState('');
  // Set when the server says this is a staff account: where it signs in.
  const [staffDoor, setStaffDoor] = useState('');
  const [loading, setLoading] = useState(false);

  const phoneValid = /^[6-9]\d{9}$/.test(phone);

  function press(digit) {
    if (pin.length >= 6 || loading) return;

    const next = pin + digit;
    setPin(next);
    setError('');

    if (next.length === 6) submit(next);
  }

  async function submit(finalPin) {
    setLoading(true);

    try {
      const response = await endpoints.auth.loginMpin(phone, finalPin, 'USER');
      signIn(response.data);
      await refresh();
      navigate('/home', { replace: true });
    } catch (err) {
      // A staff account is refused here by the server, with no session opened.
      setStaffDoor(err.code === 'WRONG_PORTAL'
        ? ({"ADMIN":"/admin/login","SUPPORT":"/support-desk/login"})[err.details?.portal] || ''
        : '');
      setError(err.message);
      setPin('');
    } finally {
      setLoading(false);
    }
  }

  if (stage === 'phone') {
    return (
      <div className="min-h-screen bg-canvas">
        <div className="mx-auto w-full max-w-md">
          <PageHeader title="" back={true} sticky={false} />

          {/* Each line arrives just behind the one above it. 60ms is enough to
              read as a sequence without making anyone wait to type - the input
              is focused immediately regardless of where its row is in the
              animation. `both` fill keeps each element hidden until its turn. */}
          <form
            className="px-6 pt-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (phoneValid) setStage('pin');
            }}
          >
            <h1 className="animate-fade-up text-2xl font-bold tracking-tight text-ink">
              Welcome back
            </h1>
            <p
              className="mt-2 animate-fade-up text-sm text-slate"
              style={{ animationDelay: '60ms' }}
            >
              Sign in with your mobile number and MPIN.
            </p>

            <div className="mt-8 animate-fade-up" style={{ animationDelay: '120ms' }}>
              <Input
                label="Mobile number"
                prefix={<span className="font-medium text-ink">+91</span>}
                inputMode="numeric"
                autoComplete="tel-national"
                autoFocus
                placeholder="98765 43210"
                value={phone}
                maxLength={10}
                onChange={(event) => setPhone(event.target.value.replace(/\D/g, '').slice(0, 10))}
              />
            </div>

            <div className="animate-fade-up" style={{ animationDelay: '180ms' }}>
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

              <button
                type="button"
                onClick={() => navigate('/signin')}
                className="mt-5 w-full text-center text-sm font-medium text-slate transition-colors duration-base ease-glide hover:text-ink"
              >
                Sign in with OTP instead
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col">
        <PageHeader
          title=""
          back={true}
          sticky={false}
          action={
            <button
              type="button"
              onClick={() => {
                setStage('phone');
                setPin('');
                setError('');
              }}
              className="text-sm font-medium text-slate hover:text-ink"
            >
              Change
            </button>
          }
        />

        <div className="flex flex-1 animate-fade-up flex-col items-center justify-center px-6 py-8">
          <h1 className="text-center text-2xl font-bold tracking-tight text-ink">
            Enter your MPIN
          </h1>
          <p className="mt-2 text-sm text-slate">+91 {phone}</p>

          <PinDots length={6} filled={pin.length} error={Boolean(error)} className="mt-10" />

          {/* Drops in rather than appearing, so a wrong PIN registers as an
              event without the layout jumping under the dots. */}
          {error && (
            <p className="mt-4 max-w-xs animate-slide-down text-center text-sm text-alert">
              {error}
            </p>
          )}
          {staffDoor && (
            <Button variant="outline" size="sm" className="mt-3" onClick={() => navigate(staffDoor)}>
              Go to staff sign-in
            </Button>
          )}
        </div>

        <div className="animate-fade-up px-6" style={{ animationDelay: '80ms' }}>
          <PinPad
            onPress={press}
            onBackspace={() => {
              setPin(pin.slice(0, -1));
              setError('');
            }}
            disabled={loading}
          />

          <div className="mb-6 flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={() => navigate(`/forgot-mpin?portal=USER&phone=${phone}`)}
              className="text-sm font-semibold text-mint-700 transition-colors duration-base ease-glide hover:text-mint-800"
            >
              Forgot MPIN?
            </button>
            <button
              type="button"
              onClick={() => navigate('/signin')}
              className="text-sm font-medium text-slate transition-colors duration-base ease-glide hover:text-ink"
            >
              Sign in with OTP instead
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
