import { useNavigate } from 'react-router-dom';

import { ListLink } from '../../components/domain';
import {
  IconBank, IconCard, IconEmi, IconLock, IconReceipt, IconShield, IconUser,
} from '../../components/layout/AppShell';
import { Badge, Button, Card, Section, Skeleton } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useProfile } from '../../hooks/useProfile';
import { date, initials, statusLabel, statusTone } from '../../utils/format';

export default function Profile() {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { profile, loading, isAdmin } = useProfile();

  if (loading || !profile) {
    return (
      <div className="space-y-4 px-4 pt-5">
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-48 w-full rounded-2xl" />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  const verified = profile.kyc_status === 'APPROVED';

  return (
    <div className="animate-fade-up pb-6">
      <header className="px-4 pt-5 pb-3">
        <h1 className="text-xl font-bold text-ink">Profile</h1>
      </header>

      <div className="space-y-5 px-4">
        {/* ── Identity ────────────────────────────────────────────────── */}
        <Card className="flex items-center gap-3.5">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-ink text-lg font-bold text-mint">
            {initials(profile.full_name)}
          </span>

          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold text-ink">
              {profile.full_name || 'Complete your profile'}
            </p>
            <p className="money truncate text-xs text-slate">+91 {profile.phone}</p>
            {profile.email && (
              <p className="truncate text-xs text-slate">{profile.email}</p>
            )}
          </div>

          <Badge tone={statusTone(profile.kyc_status)} dot className="shrink-0">
            {verified ? 'Verified' : statusLabel(profile.kyc_status)}
          </Badge>
        </Card>

        {/* ── KYC prompt ──────────────────────────────────────────────── */}
        {!verified && (
          <button
            type="button"
            onClick={() => navigate('/kyc')}
            className="flex w-full items-center gap-3 rounded-2xl border border-mint-200 bg-mint-50 p-3.5 text-left transition active:scale-[0.99]"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-mint text-ink">
              <IconShield className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">Complete your KYC</p>
              <p className="truncate text-xs text-mint-800/70">
                Unlock higher transfer limits
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-mint-800">Verify</span>
          </button>
        )}

        {/* ── Admin ───────────────────────────────────────────────────── */}
        {isAdmin && (
          <button
            type="button"
            onClick={() => navigate('/admin')}
            className="flex w-full items-center gap-3 rounded-2xl bg-ink p-3.5 text-left text-white transition active:scale-[0.99]"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/10">
              <IconLock className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">Operations console</p>
              <p className="truncate text-xs text-white/55">
                Signed in as {profile.role?.replace(/_/g, ' ')}
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-mint">Open</span>
          </button>
        )}

        {/* ── Money ───────────────────────────────────────────────────── */}
        <Section title="Money">
          <Card className="divide-y divide-line py-0">
            <ListLink
              icon={<IconCard className="h-4 w-4" />}
              label="Cards"
              description="Manage your linked credit cards"
              onClick={() => navigate('/cards')}
            />
            <ListLink
              icon={<IconBank className="h-4 w-4" />}
              label="Bank accounts"
              description="Where your transfers land"
              onClick={() => navigate('/banks')}
            />
            <ListLink
              icon={<IconEmi className="h-4 w-4" />}
              label="EMIs"
              description="Loans and auto-pay mandates"
              onClick={() => navigate('/emi')}
            />
            <ListLink
              icon={<IconReceipt className="h-4 w-4" />}
              label="Transactions"
              description="Full history and receipts"
              onClick={() => navigate('/transactions')}
            />
          </Card>
        </Section>

        {/* ── Account ─────────────────────────────────────────────────── */}
        <Section title="Account">
          <Card className="divide-y divide-line py-0">
            <ListLink
              icon={<IconShield className="h-4 w-4" />}
              label="KYC verification"
              value={verified ? 'Verified' : statusLabel(profile.kyc_status)}
              tone={verified ? 'good' : undefined}
              onClick={() => navigate('/kyc')}
            />
            <ListLink
              icon={<IconLock className="h-4 w-4" />}
              label="Security"
              description="MPIN, biometrics, active sessions"
              onClick={() => navigate('/security')}
            />
            <ListLink
              icon={<IconUser className="h-4 w-4" />}
              label="Notifications"
              description="Choose what reaches you"
              onClick={() => navigate('/notifications')}
            />
            <ListLink
              icon={<IconReceipt className="h-4 w-4" />}
              label="Help and support"
              description="Raise a ticket or track a dispute"
              onClick={() => navigate('/support')}
            />
          </Card>
        </Section>

        {/* ── Meta ────────────────────────────────────────────────────── */}
        <div className="rounded-2xl bg-mist px-4 py-3">
          <p className="text-2xs text-slate">
            Member since {date(profile.member_since)}
          </p>
          <p className="mt-0.5 text-2xs text-slate">
            KYC tier: <span className="font-medium text-ink">{profile.kyc_tier}</span>
          </p>
        </div>

        <Button
          variant="ghost"
          size="lg"
          full
          onClick={async () => {
            await signOut();
            navigate('/', { replace: true });
          }}
        >
          Sign out
        </Button>

        <p className="pb-2 text-center text-2xs text-slate-light">
          CashU v1.0 · Your cards and EMIs, under one glass pane.
        </p>
      </div>
    </div>
  );
}
