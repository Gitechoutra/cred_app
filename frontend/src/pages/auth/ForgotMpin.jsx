import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Logo } from '../../components/layout/AppShell';
import { Button, Input } from '../../components/ui';
import { useToast } from '../../context/ToastContext';

/** Where each portal signs in again after a reset. */
const SIGN_IN = {
  USER: { path: '/signin/mpin', label: 'Back to sign in' },
  ADMIN: { path: '/admin/login', label: 'Back to admin sign-in' },
  SUPPORT: { path: '/support-desk/login', label: 'Back to support sign-in' },
};

/**
 * Forgot MPIN, for all three portals.
 *
 * mobile -> OTP to that mobile -> new MPIN. The same one sign-in system as
 * everything else: no password, no email link. The server answers "if this
 * number is registered, we sent an OTP" either way, so this screen cannot be
 * used to learn who has an account. A reset signs the account out everywhere.
 */
export default function ForgotMpin() {
  const navigate = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  const portal = SIGN_IN[params.get('portal')] ? params.get('portal') : 'USER';
  const back = SIGN_IN[portal];

  const [stage, setStage] = useState('phone');           // phone | reset | done
  const [phone, setPhone] = useState((params.get('phone') || '').replace(/\D/g, '').slice(0, 10));
  const [otp, setOtp] = useState('');
  const [mpin, setMpin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const phoneValid = /^[6-9]\d{9}$/.test(phone);

  async function requestOtp(event) {
    event?.preventDefault();
    if (!phoneValid || loading) return;
    setLoading(true);
    setErrors({});
    try {
      const response = await endpoints.auth.resetMpinRequest(phone);
      // Development only: the server returns the code when there is no SMS
      // gateway, exactly as it does for sign-in.
      if (response.data?.debug_otp) setOtp(String(response.data.debug_otp));
      toast.success(response.message);
      setStage('reset');
    } catch (err) {
      setErrors({ phone: err.message });
    } finally {
      setLoading(false);
    }
  }

  async function reset(event) {
    event.preventDefault();
    const found = {};
    if (!/^\d{6}$/.test(otp)) found.otp = 'Enter the 6-digit OTP.';
    if (!/^\d{6}$/.test(mpin)) found.mpin = 'Your MPIN is 6 digits.';
    else if (mpin !== confirm) found.confirm = 'The two MPINs do not match.';
    setErrors(found);
    if (Object.keys(found).length) return;

    setLoading(true);
    try {
      await endpoints.auth.resetMpinConfirm(phone, otp, mpin);
      setStage('done');
    } catch (err) {
      const field = err.details?.field === 'mpin' ? 'mpin' : 'otp';
      setErrors({ [field]: err.message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="border-b border-line">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <button type="button" onClick={() => navigate('/')} className="flex items-center gap-2.5">
            <Logo className="h-8 w-8" />
            <span className="text-base font-bold text-ink">CashU</span>
          </button>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm animate-rise-in rounded-2xl border border-line bg-canvas p-7 shadow-card">
          {stage === 'done' ? (
            <div className="text-center">
              <div className="mx-auto grid h-14 w-14 animate-scale-in place-items-center rounded-2xl bg-mint-50 text-mint-700">
                <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <h1 className="mt-5 text-xl font-bold text-ink">MPIN reset</h1>
              <p className="mt-2 text-sm leading-relaxed text-slate">
                You have been signed out on every device. Sign in with your new MPIN.
              </p>
              <Button variant="mint" size="lg" full className="mt-6" onClick={() => navigate(back.path)}>
                {back.label}
              </Button>
            </div>
          ) : (
            <>
              <h1 className="text-2xl font-bold tracking-tight text-ink">Forgot MPIN</h1>
              <p className="mt-1.5 text-sm leading-relaxed text-slate">
                {stage === 'phone'
                  ? 'We will send an OTP to your registered mobile number.'
                  : `Enter the OTP sent to +91 ${phone} and choose a new MPIN.`}
              </p>

              {stage === 'phone' ? (
                <form onSubmit={requestOtp} className="mt-6 space-y-4">
                  <Input
                    label="Registered mobile number"
                    prefix="+91"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    autoFocus
                    placeholder="98765 43210"
                    value={phone}
                    maxLength={10}
                    error={errors.phone}
                    onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                  />
                  <Button type="submit" variant="mint" size="lg" full loading={loading} disabled={!phoneValid}>
                    Send OTP
                  </Button>
                </form>
              ) : (
                <form onSubmit={reset} className="mt-6 space-y-4">
                  <Input
                    label="OTP"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    maxLength={6}
                    value={otp}
                    error={errors.otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  />
                  <Input
                    label="New MPIN"
                    type="password"
                    inputMode="numeric"
                    autoComplete="new-password"
                    maxLength={6}
                    hint="6 digits. Avoid repeated or sequential digits."
                    value={mpin}
                    error={errors.mpin}
                    onChange={(e) => setMpin(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  />
                  <Input
                    label="Confirm new MPIN"
                    type="password"
                    inputMode="numeric"
                    autoComplete="new-password"
                    maxLength={6}
                    value={confirm}
                    error={errors.confirm}
                    onChange={(e) => setConfirm(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  />
                  <Button type="submit" variant="mint" size="lg" full loading={loading}>
                    Reset MPIN
                  </Button>
                  <button
                    type="button"
                    onClick={requestOtp}
                    className="w-full text-center text-sm font-medium text-slate hover:text-ink"
                  >
                    Resend OTP
                  </button>
                </form>
              )}

              <button
                type="button"
                onClick={() => navigate(back.path)}
                className="mt-5 w-full text-center text-sm font-semibold text-mint-700 hover:text-mint-800"
              >
                {back.label}
              </button>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
