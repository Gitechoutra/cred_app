import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Button } from '../../components/ui';
import { PageHeader } from '../../components/layout/AppShell';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { useProfile } from '../../hooks/useProfile';

const LENGTH = 6;

export default function OtpVerify() {
  const navigate = useNavigate();
  const { state } = useLocation();
  const { signIn } = useAuth();
  const { refresh } = useProfile();
  const toast = useToast();

  const phone = state?.phone;

  const [digits, setDigits] = useState(Array(LENGTH).fill(''));
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [seconds, setSeconds] = useState(state?.expiresIn || 180);
  const [resending, setResending] = useState(false);

  const inputs = useRef([]);

  useEffect(() => {
    if (!phone) navigate('/signin', { replace: true });
  }, [phone, navigate]);

  useEffect(() => {
    if (seconds <= 0) return undefined;
    const timer = setInterval(() => setSeconds((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [seconds]);

  // Development convenience: prefill the code the API handed back, so a local
  // sign-in does not require reading the server log.
  useEffect(() => {
    if (state?.debugOtp) {
      setDigits(String(state.debugOtp).slice(0, LENGTH).split(''));
    }
  }, [state?.debugOtp]);

  const code = digits.join('');

  function setDigit(index, value) {
    const char = value.replace(/\D/g, '').slice(-1);

    setDigits((current) => {
      const next = [...current];
      next[index] = char;
      return next;
    });
    setError('');

    if (char && index < LENGTH - 1) inputs.current[index + 1]?.focus();
  }

  function onKeyDown(index, event) {
    if (event.key === 'Backspace' && !digits[index] && index > 0) {
      inputs.current[index - 1]?.focus();
    }
    if (event.key === 'ArrowLeft' && index > 0) inputs.current[index - 1]?.focus();
    if (event.key === 'ArrowRight' && index < LENGTH - 1) inputs.current[index + 1]?.focus();
  }

  function onPaste(event) {
    const pasted = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, LENGTH);
    if (!pasted) return;

    event.preventDefault();
    setDigits(Array.from({ length: LENGTH }, (_, i) => pasted[i] || ''));
    inputs.current[Math.min(pasted.length, LENGTH - 1)]?.focus();
  }

  async function submit(event) {
    event?.preventDefault();
    if (code.length !== LENGTH || loading) return;

    setLoading(true);
    setError('');

    try {
      const response = await endpoints.auth.verifyOtp(phone, code, navigator.platform);
      const data = response.data;

      signIn(data);
      await refresh();

      if (data.requires_profile) navigate('/onboarding/profile', { replace: true });
      else if (data.requires_mpin) navigate('/onboarding/mpin', { replace: true });
      else navigate('/home', { replace: true });
    } catch (err) {
      setError(err.message);
      setDigits(Array(LENGTH).fill(''));
      inputs.current[0]?.focus();
    } finally {
      setLoading(false);
    }
  }

  async function resend() {
    if (resending) return;
    setResending(true);

    try {
      const response = await endpoints.auth.sendOtp(phone);
      setSeconds(response.data.expires_in_seconds || 180);
      setDigits(
        response.data.debug_otp
          ? String(response.data.debug_otp).split('')
          : Array(LENGTH).fill(''),
      );
      toast.success('A new code is on its way.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto w-full max-w-md">
        <PageHeader title="" back="/signin" sticky={false} />

        <form onSubmit={submit} className="px-6 pt-4">
          <h1 className="text-2xl font-bold tracking-tight text-ink">Enter the code</h1>
          <p className="mt-2 text-sm text-slate">
            Sent to <span className="font-medium text-ink">+91 {phone}</span>
          </p>

          <div
            className="mt-8 flex justify-between gap-2"
            onPaste={onPaste}
            role="group"
            aria-label="One-time code"
          >
            {digits.map((digit, index) => (
              <input
                key={index}
                ref={(el) => {
                  inputs.current[index] = el;
                }}
                value={digit}
                onChange={(event) => setDigit(index, event.target.value)}
                onKeyDown={(event) => onKeyDown(index, event)}
                inputMode="numeric"
                autoComplete={index === 0 ? 'one-time-code' : 'off'}
                autoFocus={index === 0}
                maxLength={1}
                aria-label={`Digit ${index + 1}`}
                className={[
                  'money h-14 w-full rounded-xl border bg-canvas text-center',
                  'text-xl font-semibold text-ink outline-none transition-all',
                  'focus:border-ink/40',
                  error ? 'border-alert' : digit ? 'border-ink/25' : 'border-line',
                ].join(' ')}
              />
            ))}
          </div>

          {error && <p className="mt-3 text-sm text-alert">{error}</p>}

          <Button
            type="submit"
            variant="mint"
            size="lg"
            full
            className="mt-6"
            disabled={code.length !== LENGTH}
            loading={loading}
          >
            Verify
          </Button>

          <div className="mt-5 text-center text-sm">
            {seconds > 0 ? (
              <p className="text-slate">
                Resend code in{' '}
                <span className="money font-medium text-ink">
                  {String(Math.floor(seconds / 60)).padStart(2, '0')}:
                  {String(seconds % 60).padStart(2, '0')}
                </span>
              </p>
            ) : (
              <button
                type="button"
                onClick={resend}
                disabled={resending}
                className="font-semibold text-mint-700 hover:text-mint-800 disabled:opacity-50"
              >
                {resending ? 'Sending...' : 'Resend code'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
