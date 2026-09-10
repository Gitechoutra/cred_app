import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader, IconLock } from '../../components/layout/AppShell';
import { Button, Card, Section, Sheet, Skeleton, Toggle } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { dateTime, statusLabel } from '../../utils/format';

export default function Security() {
  const navigate = useNavigate();
  const toast = useToast();
  const { signOut } = useAuth();
  const { profile, refresh } = useProfile();

  const { data: sessions, refetch: refetchSessions } = useFetch(
    () => endpoints.auth.sessions(),
    [],
  );
  const { data: history } = useFetch(() => endpoints.me.loginHistory(), []);

  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [busy, setBusy] = useState(false);

  const security = profile?.security;

  async function toggle(field, value) {
    try {
      await endpoints.me.security({ [field]: value });
      await refresh();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function revokeAll() {
    setBusy(true);
    try {
      await endpoints.auth.revokeAll();
      toast.success('All sessions signed out.');
      await signOut();
      navigate('/', { replace: true });
    } catch (err) {
      toast.error(err.message);
      setBusy(false);
    }
  }

  if (!profile) {
    return (
      <div className="">
        <PageHeader title="Security" back="/profile" />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Security" back="/profile" />

        <div className="space-y-5 px-4 pt-4">
          <Section title="Sign-in">
            <Card className="divide-y divide-line py-0">
              <Toggle
                label="Biometric unlock"
                description="Use fingerprint or face to open CashU"
                checked={Boolean(security?.biometric_enabled)}
                onChange={(value) => toggle('biometric_enabled', value)}
              />
              <Toggle
                label="Sign-in alerts"
                description="Tell me when a new device signs in"
                checked={Boolean(security?.login_alerts_enabled)}
                onChange={(value) => toggle('login_alerts_enabled', value)}
              />
              <Toggle
                label="Two-factor authentication"
                description="Require OTP for sensitive changes"
                checked={Boolean(security?.two_factor_enabled)}
                onChange={(value) => toggle('two_factor_enabled', value)}
              />
            </Card>
          </Section>

          <Section title="MPIN">
            <Card>
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mist text-slate">
                  <IconLock className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink">6-digit MPIN</p>
                  <p className="text-xs text-slate">
                    {security?.mpin_last_changed
                      ? `Last changed ${dateTime(security.mpin_last_changed)}`
                      : 'Set up and active'}
                  </p>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                full
                className="mt-3"
                onClick={() => navigate('/onboarding/mpin')}
              >
                Change MPIN
              </Button>
            </Card>
          </Section>

          {/* ── Sessions ────────────────────────────────────────────── */}
          <Section title="Active sessions">
            <Card className="divide-y divide-line py-0">
              {(sessions || []).map((session) => (
                <div key={session.session_id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {session.device_name || 'Unknown device'}
                      {session.is_current && (
                        <span className="ml-1.5 text-2xs font-semibold text-mint-700">
                          This device
                        </span>
                      )}
                    </p>
                    <p className="money truncate text-2xs text-slate">
                      {session.ip_address} · {dateTime(session.last_used_at)}
                    </p>
                  </div>
                </div>
              ))}

              {(!sessions || sessions.length === 0) && (
                <p className="py-4 text-center text-sm text-slate">No active sessions.</p>
              )}
            </Card>

            <Button variant="ghost" size="md" full onClick={() => setConfirmRevoke(true)}>
              Sign out of all devices
            </Button>
          </Section>

          {/* ── Recent activity ─────────────────────────────────────── */}
          {history?.length > 0 && (
            <Section title="Recent sign-in attempts">
              <Card className="divide-y divide-line py-0">
                {history.slice(0, 8).map((entry) => (
                  <div key={entry.login_id} className="flex items-center gap-3 py-2.5">
                    <span
                      className={[
                        'h-1.5 w-1.5 shrink-0 rounded-full',
                        entry.status === 'SUCCESS' ? 'bg-mint-600' : 'bg-alert',
                      ].join(' ')}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-ink">
                        {statusLabel(entry.status)}
                      </p>
                      <p className="money truncate text-2xs text-slate">
                        {entry.ip_address} · {dateTime(entry.created_on)}
                      </p>
                    </div>
                  </div>
                ))}
              </Card>
            </Section>
          )}
        </div>
      </div>

      <Sheet
        open={confirmRevoke}
        onClose={() => setConfirmRevoke(false)}
        title="Sign out everywhere?"
        footer={
          <div className="flex gap-2">
            <Button variant="outline" size="lg" full onClick={() => setConfirmRevoke(false)}>
              Cancel
            </Button>
            <Button variant="danger" size="lg" full loading={busy} onClick={revokeAll}>
              Sign out all
            </Button>
          </div>
        }
      >
        <p className="pb-2 text-sm leading-relaxed text-slate">
          Every device, including this one, will be signed out immediately. Use
          this if you think someone else has access to your account.
        </p>
      </Sheet>
    </div>
  );
}
