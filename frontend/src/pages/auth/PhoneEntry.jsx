import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Button, Input } from '../../components/ui';
import { PageHeader } from '../../components/layout/AppShell';
import { useToast } from '../../context/ToastContext';

export default function PhoneEntry() {
  const navigate = useNavigate();
  const toast = useToast();

  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const valid = /^[6-9]\d{9}$/.test(phone);

  async function submit(event) {
    event.preventDefault();
    if (!valid || loading) return;

    setLoading(true);
    setError('');

    try {
      const response = await endpoints.auth.sendOtp(phone);

      navigate('/signin/otp', {
        state: {
          phone,
          isNewUser: response.data.is_new_user,
          expiresIn: response.data.expires_in_seconds,
          // Development only - the backend returns the code when there is no
          // live SMS gateway, so a local sign-in is actually completable.
          debugOtp: response.data.debug_otp,
        },
      });
    } catch (err) {
      setError(err.message);
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto w-full max-w-md">
        <PageHeader title="" back="/" sticky={false} />

        <form onSubmit={submit} className="px-6 pt-4">
          <h1 className="text-2xl font-bold tracking-tight text-ink">
            What&rsquo;s your mobile number?
          </h1>
          <p className="mt-2 text-sm text-slate">
            We&rsquo;ll send a 6-digit code to verify it&rsquo;s you.
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
              error={error}
              onChange={(event) => {
                setPhone(event.target.value.replace(/\D/g, '').slice(0, 10));
                setError('');
              }}
            />
          </div>

          <Button
            type="submit"
            variant="mint"
            size="lg"
            full
            className="mt-6"
            disabled={!valid}
            loading={loading}
          >
            Send code
          </Button>

          <div className="mt-8 flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3">
            <svg viewBox="0 0 24 24" className="mt-0.5 h-4 w-4 shrink-0 text-slate" fill="none">
              <path
                d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
            <p className="text-xs leading-relaxed text-slate">
              Your number is used only to verify your identity and secure your
              account. We never share it.
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
