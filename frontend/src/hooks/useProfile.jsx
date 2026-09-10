import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { endpoints } from '../api/client';
import { useAuth } from '../context/AuthContext';

/**
 * The signed-in user's profile.
 *
 * Kept apart from AuthContext on purpose: auth owns the token pair, this owns
 * who the token belongs to. The profile is always re-fetched from the server
 * rather than decoded from the JWT, so a role change, a KYC approval or an
 * account freeze takes effect on the next load instead of at token expiry.
 */

const ProfileContext = createContext(null);

const ADMIN_ROLES = ['L1_SUPPORT', 'L2_RISK_RECON', 'L3_SUPER_ADMIN'];

export function ProfileProvider({ children }) {
  const { isAuthenticated } = useAuth();

  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(isAuthenticated);

  const load = useCallback(async () => {
    if (!isAuthenticated) {
      setProfile(null);
      setLoading(false);
      return null;
    }

    try {
      const response = await endpoints.me.get();
      setProfile(response.data);
      return response.data;
    } catch {
      setProfile(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    setLoading(isAuthenticated);
    load();
  }, [isAuthenticated, load]);

  const value = useMemo(
    () => ({
      profile,
      loading,
      refresh: load,
      isAdmin: Boolean(profile && ADMIN_ROLES.includes(profile.role)),
      role: profile?.role || null,
      kycTier: profile?.kyc_tier || 'NONE',
      kycStatus: profile?.kyc_status || 'NOT_STARTED',
      needsProfile: Boolean(profile && !profile.full_name),
      needsMpin: Boolean(profile && !profile.mpin_set),
      firstName: (profile?.full_name || '').split(' ')[0] || 'there',
    }),
    [profile, loading, load],
  );

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile() {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfile must be used inside a ProfileProvider.');
  }
  return context;
}

/* ── Data fetching ──────────────────────────────────────────────────────── */

/**
 * Minimal async data hook.
 *
 * Enough for this app's read patterns without pulling in a query library: one
 * request, loading and error state, and a refetch. `deps` controls re-running.
 */
export function useFetch(fn, deps = [], { skip = false } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(!skip);

  const run = useCallback(async () => {
    if (skip) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fn();
      setData(response?.data ?? response);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, ...deps]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (skip) {
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const response = await fn();
        if (!cancelled) setData(response?.data ?? response);
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, ...deps]);

  return { data, error, loading, refetch: run, setData };
}
