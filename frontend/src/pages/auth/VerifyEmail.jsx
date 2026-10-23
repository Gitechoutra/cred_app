import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { Logo } from '../../components/layout/AppShell';
import { Button, Loader3D } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';

/**
 * Lands from the verification email. Works signed in or not: the link's
 * signed token is the whole proof, so it can be opened on any device.
 */
export default function VerifyEmail() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [params] = useSearchParams();
  const [state, setState] = useState({ status: 'checking', message: '' });
  const sent = useRef(false);

  useEffect(() => {
    // Once only - React's development double-invoke would otherwise send the
    // token twice and show the second, "already verified" answer.
    if (sent.current) return;
    sent.current = true;
    const token = params.get('token');
    if (!token) {
      setState({ status: 'error', message: 'This link is missing its token.' });
      return;
    }
    endpoints.auth.verifyEmail(token)
      .then((response) => setState({ status: 'ok', message: `${response.data.email} is verified.` }))
      .catch((err) => setState({ status: 'error', message: err.message }));
  }, [params]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm animate-rise-in rounded-2xl border border-line p-7 text-center shadow-card">
        <Logo className="mx-auto h-10 w-10" />
        {state.status === 'checking' ? (
          <div className="mt-6 flex flex-col items-center">
            <Loader3D />
            <p className="mt-4 text-sm text-slate">Verifying your email…</p>
          </div>
        ) : (
          <>
            <h1 className="mt-5 text-xl font-bold text-ink">
              {state.status === 'ok' ? 'Email verified' : 'Could not verify'}
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-slate">{state.message}</p>
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-6"
              onClick={() => navigate(isAuthenticated ? '/profile' : '/signin/mpin')}
            >
              {isAuthenticated ? 'Back to profile' : 'Sign in'}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
