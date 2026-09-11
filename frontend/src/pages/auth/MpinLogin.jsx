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
      const response = await endpoints.auth.loginMpin(phone, finalPin);
      signIn(response.data);
      await refresh();

      // Always the member app. Staff who want the console either came through
      // /admin/login or can switch from the sidebar - honouring the door they
      // actually chose is less surprising than redirecting them.
      navigate('/home', { replace: true });
    } catch (err) {
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
          <PageHeader title="" back="/" sticky={false} />

          <form
            className="px-6 pt-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (phoneValid) setStage('pin');
            }}
          >
            <h1 className="text-2xl font-bold tracking-tight text-ink">Welcome back</h1>
            <p className="mt-2 text-sm text-slate">
              Sign in with your mobile number and MPIN.
            </p>

            <div className="mt-8">
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
              className="mt-5 w-full text-center text-sm font-medium text-slate hover:text-ink"
            >
              Sign in with OTP instead
            </button>
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
          back={undefined}
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

        <div className="flex flex-1 flex-col items-center justify-center px-6 py-8">
          <h1 className="text-center text-2xl font-bold tracking-tight text-ink">
            Enter your MPIN
          </h1>
          <p className="mt-2 text-sm text-slate">+91 {phone}</p>

          <PinDots length={6} filled={pin.length} error={Boolean(error)} className="mt-10" />

          {error && <p className="mt-4 max-w-xs text-center text-sm text-alert">{error}</p>}
        </div>

        <div className="px-6">
          <PinPad
            onPress={press}
            onBackspace={() => {
              setPin(pin.slice(0, -1));
              setError('');
            }}
            disabled={loading}
          />

          <button
            type="button"
            onClick={() => navigate('/signin')}
            className="mb-6 w-full text-center text-sm font-medium text-slate hover:text-ink"
          >
            Forgot MPIN? Sign in with OTP
          </button>
        </div>
      </div>
    </div>
  );
}
