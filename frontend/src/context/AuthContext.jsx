import { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { endpoints, tokens } from '../api/client';

/**
 * Session state for the app shell.
 *
 * Deliberately thin. The token pair is the only thing held here, and the
 * backend remains the authority on what it may do - nothing about KYC tier,
 * limits or feature flags is cached, because a stale copy of "you are allowed
 * to transfer" is a security decision made in the wrong place.
 *
 * Access-token refresh is not handled here either. The API client already does
 * it transparently on a 401, so a user mid-transfer is never bounced to a login
 * screen by a 15-minute expiry they cannot see.
 */

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [accessToken, setAccessToken] = useState(() => tokens.access);

  const signIn = useCallback((tokenPair) => {
    tokens.set(tokenPair);
    setAccessToken(tokenPair?.access_token ?? null);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await endpoints.auth.logout();
    } catch {
      // A failed logout call must not strand the user in a signed-in shell -
      // clearing the local tokens is what actually ends the session here.
    } finally {
      tokens.clear();
      setAccessToken(null);
    }
  }, []);

  const value = useMemo(
    () => ({
      accessToken,
      isAuthenticated: Boolean(accessToken),
      signIn,
      signOut,
    }),
    [accessToken, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider');
  return context;
}
