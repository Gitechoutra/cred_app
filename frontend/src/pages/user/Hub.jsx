import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardTile, DueItem, EmiRow, TransactionRow } from '../../components/domain';
import {
  IconAlert,
  IconBank,
  IconCard,
  IconChart,
  IconCheck,
  IconChevron,
  IconClock,
  IconEmi,
  IconHelp,
  IconLock,
  IconPlus,
  IconQr,
  IconReceipt,
  IconShield,
  IconUser,
} from '../../components/layout/AppShell';
import {
  AnimatedMoney,
  Badge,
  Button,
  Card,
  EmptyState,
  Section,
  Skeleton,
  cx,
} from '../../components/ui';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { Reveal } from '../../hooks/useReveal';
import { money, moneyCompact } from '../../utils/format';

/**
 * Premium CashU Logged-In User Home Experience.
 *
 * Classic fintech / MNC-grade financial dashboard:
 * 1. Executive welcome & portfolio health overview
 * 2. Obsidian financial overview with live debt, available credit & utilisation
 * 3. Urgent next-due payment spotlight or "All caught up" milestone
 * 4. Rapid fintech quick actions dock
 * 5. Monthly EMI & debt commitments strip
 * 6. Linked cards preview
 * 7. Active EMIs & recent activity ledger
 * 8. Intelligently organized account & money features
 */

export default function Hub() {
  const navigate = useNavigate();
  const { profile, isAdmin, kycStatus, firstName } = useProfile();
  const { data, loading, error, refetch } = useFetch(() => endpoints.dashboard.get(), []);

  if (loading) return <HubSkeleton />;

  // Gracefully fallback if network fails
  const summary = data?.summary || {
    total_debt: 0,
    total_available_credit: 0,
    total_credit_limit: 0,
    credit_utilization_percentage: null,
    utilization_badge: { label: 'Not tracked', tone: 'neutral' },
    monthly_emi_commitment: 0,
    emi_outstanding: 0,
    total_outstanding_amount: 0,
  };

  const badge = summary.utilization_badge || { label: 'Optimal', tone: 'good' };
  const counts = data?.counts || {
    cards: 0,
    emi_obligations: 0,
    verified_bank_accounts: 0,
    active_mandates: 0,
  };
  const quickActions = data?.quick_actions || {
    can_pay_emi: true,
    needs_kyc: false,
    needs_bank_account: false,
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-7 pb-6 sm:space-y-9 animate-fade-up">
      {/* ── 1. Executive Welcome & Header ────────────────────────────── */}
      <section className="flex flex-col justify-between gap-4 rounded-3xl border border-line/70 bg-gradient-to-r from-canvas via-mist/50 to-mint-50/20 p-5 shadow-card sm:flex-row sm:items-center sm:p-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-mint-200 bg-mint-50 px-2.5 py-0.5 text-2xs font-semibold text-mint-800">
              <span className="h-1.5 w-1.5 rounded-full bg-mint-600 animate-pulse" />
              {kycStatus === 'APPROVED' ? 'Verified Account' : 'Account active'}
            </span>
            <span className="text-2xs text-slate">·</span>
            <span className="text-2xs font-medium text-slate">
              {counts.cards} {counts.cards === 1 ? 'card' : 'cards'} linked
            </span>
            <span className="text-2xs text-slate">·</span>
            <span className="text-2xs font-medium text-slate">
              {counts.emi_obligations} active {counts.emi_obligations === 1 ? 'EMI' : 'EMIs'}
            </span>
          </div>

          <h1 className="text-xl font-bold tracking-tight text-ink sm:text-2xl">
            {timeGreeting()}, {firstName}
          </h1>
          <p className="text-xs text-slate sm:text-sm">
            Everything you owe, track, and move — unified in one executive pane.
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2.5 pt-1 sm:pt-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/cards/add')}
            className="rounded-xl border-line bg-canvas hover:border-mint-600/40 hover:bg-mint-50/30"
          >
            <IconPlus className="h-3.5 w-3.5 text-mint-700" />
            <span>Add card</span>
          </Button>
        </div>
      </section>

      {/* ── Setup Prompts (if KYC or Bank account needed) ─────────────── */}
      {quickActions.needs_kyc && (
        <SetupBanner
          icon={<IconShield className="h-5 w-5 text-ink" />}
          title="Verify your identity to unlock full limits"
          description="RBI compliance requires identity verification before moving funds or unlocking higher limits."
          cta="Verify now"
          onClick={() => navigate('/kyc')}
        />
      )}

      {!quickActions.needs_kyc && quickActions.needs_bank_account && (
        <SetupBanner
          icon={<IconBank className="h-5 w-5 text-ink" />}
          title="Add and verify a payout bank account"
          description="Link an account via penny-drop verification to receive card-to-bank settlement funds."
          cta="Add bank account"
          onClick={() => navigate('/banks/add')}
        />
      )}

      {/* ── 2. Hero Financial Overview & Next Due Spotlight ───────────── */}
      <div className="grid gap-5 lg:grid-cols-12">
        {/* Left: Obsidian Financial Portfolio Card */}
        <section className="relative overflow-hidden rounded-3xl bg-[#0A0F0D] p-6 text-white shadow-[0_16px_40px_-16px_rgba(10,15,13,0.3)] border border-white/10 lg:col-span-8 sm:p-8">
          {/* Subtle light blooms and hairlines */}
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent"
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full bg-mint/15 blur-3xl"
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -left-12 -bottom-16 h-48 w-48 rounded-full bg-mint/10 blur-2xl"
          />

          <div className="relative flex flex-col justify-between gap-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-mint" />
                  <p className="text-2xs font-semibold uppercase tracking-widest text-white/60">
                    Total Portfolio Exposure
                  </p>
                </div>

                <AnimatedMoney
                  value={summary.total_debt}
                  format={(v) => money(v)}
                  className="mt-2 block text-3xl font-extrabold tracking-tight text-white sm:text-4xl"
                />

                <p className="mt-1.5 text-xs text-white/50">
                  Obligations across {counts.cards} card{counts.cards === 1 ? '' : 's'} and{' '}
                  {counts.emi_obligations} loan{counts.emi_obligations === 1 ? '' : 's'}
                </p>
              </div>

              {/* High-level metrics */}
              <div className="grid grid-cols-2 gap-4 rounded-2xl border border-white/10 bg-white/[0.04] p-3.5 sm:gap-6 sm:p-4">
                <div>
                  <p className="text-2xs font-medium uppercase tracking-wider text-white/50">
                    Available Credit
                  </p>
                  <p className="money mt-1 text-lg font-bold text-mint sm:text-xl">
                    {money(summary.total_available_credit)}
                  </p>
                </div>
                <div>
                  <p className="text-2xs font-medium uppercase tracking-wider text-white/50">
                    Total Credit Limit
                  </p>
                  <p className="money mt-1 text-lg font-semibold text-white/90 sm:text-xl">
                    {moneyCompact(summary.total_credit_limit)}
                  </p>
                </div>
              </div>
            </div>

            {/* Credit Utilisation Gauge */}
            {summary.credit_utilization_percentage !== null && (
              <div className="relative border-t border-white/10 pt-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-white/60">
                      Credit Utilisation
                    </span>
                    <span className="text-2xs text-white/40">
                      ({summary.credit_utilization_percentage}% of aggregate limit)
                    </span>
                  </div>

                  <span
                    className={cx(
                      'rounded-full px-2.5 py-0.5 text-2xs font-bold tracking-wide uppercase',
                      badge.tone === 'good' && 'bg-mint text-ink shadow-[0_0_12px_rgba(0,245,184,0.4)]',
                      badge.tone === 'neutral' && 'bg-white/15 text-white',
                      badge.tone === 'warn' && 'bg-warn text-ink',
                      badge.tone === 'alert' && 'bg-alert text-white',
                    )}
                  >
                    {badge.label}
                  </span>
                </div>

                <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-white/10 p-0.5">
                  <div
                    className={cx(
                      'h-full rounded-full transition-all duration-700 ease-glide',
                      badge.tone === 'good' && 'bg-gradient-to-r from-mint-300 to-mint',
                      badge.tone === 'neutral' && 'bg-white/70',
                      badge.tone === 'warn' && 'bg-warn',
                      badge.tone === 'alert' && 'bg-alert',
                    )}
                    style={{
                      width: `${Math.min(100, Math.max(3, summary.credit_utilization_percentage || 0))}%`,
                    }}
                  />
                </div>

                <div className="mt-2 flex items-center justify-between text-2xs text-white/40">
                  <span>Target: Under 30% for optimal CIBIL score</span>
                  <span>Max: 100%</span>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Right: Next Due Item Spotlight or All Caught Up */}
        <div className="lg:col-span-4">
          {data?.next_due_item ? (
            <NextDueSpotlight
              item={data.next_due_item}
              onPay={() =>
                navigate(
                  data.next_due_item.type === 'EMI'
                    ? `/emi/${data.next_due_item.id}/pay`
                    : `/cards/${data.next_due_item.id}`,
                )
              }
            />
          ) : (
            <section className="flex h-full flex-col justify-between rounded-3xl border border-line/80 bg-gradient-to-b from-canvas to-mist/40 p-6 text-center shadow-card">
              <div className="my-auto space-y-3 py-4">
                <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-mint-50 text-mint-700 ring-1 ring-mint-200">
                  <IconCheck className="h-7 w-7" />
                </span>
                <div className="space-y-1">
                  <h3 className="text-base font-bold text-ink">All caught up</h3>
                  <p className="mx-auto max-w-xs text-xs text-slate">
                    No card bills or EMI installments scheduled in the next 30 days. Your accounts are in optimal standing.
                  </p>
                </div>
              </div>

              <div className="border-t border-line/80 pt-4">
                <Button
                  variant="outline"
                  size="sm"
                  full
                  onClick={() => navigate('/dashboard')}
                  className="rounded-xl"
                >
                  View full debt breakdown
                </Button>
              </div>
            </section>
          )}
        </div>
      </div>

      {/* ── 3. Rapid Fintech Quick Actions Dock ───────────────────────── */}
      <section className="rounded-3xl border border-line/80 bg-canvas p-4 shadow-card sm:p-5">
        <div className="mb-3.5 flex items-center justify-between px-1">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
            Quick Actions
          </p>
          <span className="text-2xs font-medium text-slate-light">
            Instant operations
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5 sm:gap-3">
          <QuickActionBtn
            icon={IconQr}
            title="Scan &amp; Pay"
            hint="UPI QR Code"
            onClick={() => navigate('/scan')}
          />
          <QuickActionBtn
            icon={IconEmi}
            title="Pay EMI"
            hint="Installments"
            onClick={() => navigate('/emi')}
          />
          <QuickActionBtn
            icon={IconCard}
            title="Add Card"
            hint="Tokenised CoF"
            onClick={() => navigate('/cards/add')}
          />
          <QuickActionBtn
            icon={IconBank}
            title="Add Bank"
            hint="Payout account"
            onClick={() => navigate('/banks/add')}
          />
        </div>
      </section>

      {/* ── 4. Monthly Commitment & Balance Strip ─────────────────────── */}
      <div className="grid gap-3 sm:grid-cols-3">
        <StatMetricCard
          label="Monthly EMI commitment"
          value={money(summary.monthly_emi_commitment)}
          hint={`${counts.emi_obligations} ongoing installment schedule${counts.emi_obligations === 1 ? '' : 's'}`}
          icon={IconEmi}
          onClick={() => navigate('/emi')}
        />
        <StatMetricCard
          label="Total EMI outstanding"
          value={money(summary.emi_outstanding)}
          hint="Aggregate principal balance"
          icon={IconChart}
          onClick={() => navigate('/dashboard')}
        />
        <StatMetricCard
          label="Total Card outstanding"
          value={money(summary.total_outstanding_amount)}
          hint={`Across ${counts.cards} linked credit instrument${counts.cards === 1 ? '' : 's'}`}
          icon={IconCard}
          onClick={() => navigate('/cards')}
        />
      </div>

      {/* ── 5. Linked Cards Snapshot ─────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-baseline justify-between px-1">
          <div>
            <h2 className="text-base font-bold tracking-tight text-ink sm:text-lg">
              Linked Cards
            </h2>
            <p className="text-2xs text-slate">
              RBI Card-on-File tokenised credit accounts with real-time limits
            </p>
          </div>

          <button
            type="button"
            onClick={() => navigate('/cards')}
            className="flex items-center gap-1 text-xs font-semibold text-mint-700 transition hover:text-mint-800"
          >
            <span>Manage cards ({counts.cards})</span>
            <IconChevron className="h-3.5 w-3.5" />
          </button>
        </div>

        {data?.cards && data.cards.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.cards.slice(0, 3).map((card) => (
              <CardTile
                key={card.card_id}
                card={card}
                onClick={() => navigate(`/cards/${card.card_id}`)}
              />
            ))}

            {data.cards.length < 3 && (
              <button
                type="button"
                onClick={() => navigate('/cards/add')}
                className="group flex min-h-[156px] flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed border-line bg-canvas p-4 text-center transition-all duration-base ease-glide hover:border-mint-600/40 hover:bg-mint-50/30 hover:shadow-card active:scale-[0.985]"
              >
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-mint-50 text-mint-700 transition-transform group-hover:scale-110">
                  <IconPlus className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-xs font-semibold text-ink">Link another credit card</p>
                  <p className="mt-0.5 text-2xs text-slate">Visa, Mastercard, RuPay &amp; Diners</p>
                </div>
              </button>
            )}
          </div>
        ) : (
          <Card className="border-dashed py-8 text-center">
            <EmptyState
              icon={<IconCard className="h-8 w-8 text-mint-600" />}
              title="No credit cards linked yet"
              description="Add your cards to track available limits, due dates and statements in one place."
              action={
                <Button variant="mint" size="sm" onClick={() => navigate('/cards/add')}>
                  <IconPlus className="h-4 w-4" />
                  Add your first card
                </Button>
              }
            />
          </Card>
        )}
      </section>

      {/* ── 6. Active EMIs & Recent Activity (Side-by-Side) ───────────── */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left Column: Active EMIs */}
        <section className="flex flex-col space-y-3.5">
          <div className="flex items-baseline justify-between px-1">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold tracking-tight text-ink">
                Active EMIs &amp; Loans
              </h2>
              {counts.emi_obligations > 0 && (
                <Badge tone="good">{counts.emi_obligations} Active</Badge>
              )}
            </div>

            <button
              type="button"
              onClick={() => navigate('/emi')}
              className="flex items-center gap-1 text-xs font-semibold text-mint-700 transition hover:text-mint-800"
            >
              <span>View all</span>
              <IconChevron className="h-3.5 w-3.5" />
            </button>
          </div>

          {data?.emi_obligations && data.emi_obligations.length > 0 ? (
            <div className="space-y-2.5">
              {data.emi_obligations.slice(0, 3).map((emi) => (
                <EmiRow
                  key={emi.emi_id}
                  emi={emi}
                  onClick={() => navigate(`/emi/${emi.emi_id}`)}
                />
              ))}
            </div>
          ) : (
            <Card className="flex flex-1 flex-col justify-center border-dashed py-7 text-center">
              <EmptyState
                icon={<IconEmi className="h-6 w-6 text-slate" />}
                title="No EMIs tracked"
                description="Add personal, auto, or home loans to track installments."
                action={
                  <Button variant="outline" size="sm" onClick={() => navigate('/emi/add')}>
                    <IconPlus className="h-3.5 w-3.5" />
                    Add an EMI
                  </Button>
                }
              />
            </Card>
          )}
        </section>

        {/* Right Column: Recent Activity Ledger */}
        <section className="flex flex-col space-y-3.5">
          <div className="flex items-baseline justify-between px-1">
            <h2 className="text-base font-bold tracking-tight text-ink">
              Recent Activity
            </h2>

            <button
              type="button"
              onClick={() => navigate('/transactions')}
              className="flex items-center gap-1 text-xs font-semibold text-mint-700 transition hover:text-mint-800"
            >
              <span>All activity</span>
              <IconChevron className="h-3.5 w-3.5" />
            </button>
          </div>

          {data?.recent_transactions && data.recent_transactions.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-line/80 bg-canvas shadow-card divide-y divide-line/70 px-3">
              {data.recent_transactions.slice(0, 4).map((tx) => (
                <TransactionRow
                  key={tx.transaction_id}
                  transaction={tx}
                  onClick={() => navigate(`/transactions/${tx.transaction_id}`)}
                />
              ))}
            </div>
          ) : (
            <Card className="flex flex-1 flex-col justify-center border-dashed py-7 text-center">
              <EmptyState
                icon={<IconReceipt className="h-6 w-6 text-slate" />}
                title="No transactions yet"
                description="Your card spends, QR scan payments, and EMI records will appear here."
              />
            </Card>
          )}
        </section>
      </div>

      {/* ── 7. Intelligently Organized Hub & Account Features ─────────── */}
      <section className="space-y-4 pt-2">
        <div className="flex items-baseline justify-between px-1">
          <div>
            <h2 className="text-base font-bold tracking-tight text-ink sm:text-lg">
              Services &amp; Account Features
            </h2>
            <p className="text-2xs text-slate">
              Complete access to banking rails, credit analytics, and security controls
            </p>
          </div>
        </div>

        <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          <QuickServiceCard
            icon={IconChart}
            title="Dashboard Overview"
            hint="Telemetry &amp; analytics"
            onClick={() => navigate('/dashboard')}
          />
          <QuickServiceCard
            icon={IconCard}
            title="Cards Hub"
            hint={`${counts.cards} Linked credit cards`}
            onClick={() => navigate('/cards')}
          />
          <QuickServiceCard
            icon={IconBank}
            title="Bank Accounts"
            hint={`${counts.verified_bank_accounts} Verified accounts`}
            onClick={() => navigate('/banks')}
          />
          <QuickServiceCard
            icon={IconReceipt}
            title="History &amp; Receipts"
            hint="Transaction statements"
            onClick={() => navigate('/transactions')}
          />
          <QuickServiceCard
            icon={IconUser}
            title="Member Profile"
            hint="Personal &amp; KYC tier"
            onClick={() => navigate('/profile')}
          />
          <QuickServiceCard
            icon={IconShield}
            title="KYC Verification"
            hint={kycStatus === 'APPROVED' ? 'Verified Tier 1' : 'Complete verification'}
            onClick={() => navigate('/kyc')}
          />
          <QuickServiceCard
            icon={IconLock}
            title="Security &amp; MPIN"
            hint="Devices &amp; credentials"
            onClick={() => navigate('/security')}
          />
          <QuickServiceCard
            icon={IconHelp}
            title="Help &amp; Support"
            hint="24/7 dedicated support"
            onClick={() => navigate('/support')}
          />

          {isAdmin && (
            <QuickServiceCard
              icon={IconShield}
              title="Operations Console"
              hint="Admin tools &amp; audits"
              onClick={() => navigate('/admin')}
              highlight
            />
          )}
        </div>
      </section>
    </div>
  );
}

/* ── UI Building Blocks ─────────────────────────────────────────────────── */

function QuickActionBtn({ icon: Icon, title, hint, onClick, primary = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'group relative flex flex-col items-center justify-center gap-2 rounded-2xl p-3 text-center transition-all duration-base ease-glide',
        'border active:scale-95',
        primary
          ? 'border-mint-200/80 bg-mint-50/50 hover:bg-mint-50 hover:border-mint-300 hover:shadow-mint'
          : 'border-line/70 bg-canvas hover:border-mint-500/30 hover:bg-mist/60 hover:shadow-card',
      )}
    >
      <span
        className={cx(
          'grid h-11 w-11 place-items-center rounded-xl transition-all duration-base ease-glide',
          primary
            ? 'bg-mint text-ink shadow-sm group-hover:scale-105'
            : 'bg-mist text-slate group-hover:bg-mint group-hover:text-ink group-hover:scale-105',
        )}
      >
        <Icon className="h-5 w-5" />
      </span>

      <div className="min-w-0">
        <span className="block truncate text-xs font-semibold text-ink">
          {title}
        </span>
        <span className="block truncate text-[10.5px] text-slate">
          {hint}
        </span>
      </div>
    </button>
  );
}

function StatMetricCard({ label, value, hint, icon: Icon, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col justify-between rounded-2xl border border-line/80 bg-canvas p-4 text-left shadow-card transition-all duration-base ease-glide hover:-translate-y-0.5 hover:border-mint-600/30 hover:shadow-lift active:translate-y-0 active:scale-[0.99]"
    >
      <div className="flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-wider text-slate">
          {label}
        </span>
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-mist text-slate transition-colors group-hover:bg-mint-50 group-hover:text-mint-700">
          <Icon className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-3">
        <p className="money text-2xl font-bold tracking-tight text-ink">
          {value}
        </p>
        <p className="mt-1 text-2xs text-slate transition-colors group-hover:text-mint-800">
          {hint}
        </p>
      </div>
    </button>
  );
}

function NextDueSpotlight({ item, onPay }) {
  const overdue = item.is_overdue;
  const urgent = !overdue && item.days_remaining <= 3;

  return (
    <section
      className={cx(
        'relative flex h-full flex-col justify-between overflow-hidden rounded-3xl border p-6 shadow-card transition-all duration-base',
        overdue
          ? 'border-alert/40 bg-gradient-to-br from-red-50/50 to-canvas'
          : urgent
            ? 'border-warn/40 bg-gradient-to-br from-amber-50/50 to-canvas'
            : 'border-line/80 bg-gradient-to-br from-canvas to-mist/30',
      )}
    >
      <div>
        <div className="flex items-center justify-between gap-2">
          <span
            className={cx(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-2xs font-bold uppercase tracking-wider',
              overdue
                ? 'bg-red-100 text-alert'
                : urgent
                  ? 'bg-amber-100 text-amber-800'
                  : 'bg-mint-50 text-mint-800 border border-mint-200',
            )}
          >
            {overdue ? (
              <>
                <IconAlert className="h-3 w-3 text-alert" />
                Overdue
              </>
            ) : (
              <>
                <IconClock className="h-3 w-3 text-mint-700" />
                Next Payment Due
              </>
            )}
          </span>

          <span className="text-2xs font-semibold text-slate">
            {overdue
              ? `${Math.abs(item.days_remaining)} days late`
              : item.days_remaining === 0
                ? 'Due today'
                : `In ${item.days_remaining} days`}
          </span>
        </div>

        <div className="mt-4">
          <p className="truncate text-base font-bold text-ink">{item.title}</p>
          <p className="truncate text-xs text-slate">{item.subtitle}</p>

          <p className="money mt-3 text-3xl font-extrabold tracking-tight text-ink">
            {money(item.amount)}
          </p>

          {item.minimum_due ? (
            <p className="mt-1 text-2xs text-slate">
              Minimum due:{' '}
              <span className="money font-semibold text-ink">
                {money(item.minimum_due)}
              </span>
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-6 border-t border-line/70 pt-4">
        <Button
          variant={overdue ? 'danger' : 'mint'}
          size="md"
          full
          onClick={onPay}
          className="rounded-xl shadow-sm"
        >
          {item.type === 'EMI' ? 'Pay EMI installment' : 'Pay card bill'}
        </Button>
      </div>
    </section>
  );
}

function FeatureCard({ icon: Icon, title, badge, description, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative flex flex-col justify-between rounded-2xl border border-line/80 bg-canvas p-4 text-left shadow-card transition-all duration-base ease-glide hover:-translate-y-0.5 hover:border-mint-500/30 hover:shadow-lift active:translate-y-0 active:scale-[0.99]"
    >
      <div className="flex items-start justify-between">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-mint-50 text-mint-700 ring-1 ring-inset ring-mint-500/20 transition-all duration-base group-hover:scale-105 group-hover:bg-mint group-hover:text-ink">
          <Icon className="h-5 w-5" />
        </span>
        {badge && (
          <span className="rounded-full bg-mint-50 border border-mint-200 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-mint-800">
            {badge}
          </span>
        )}
      </div>

      <div className="mt-4">
        <p className="text-sm font-bold text-ink">{title}</p>
        <p className="mt-0.5 text-xs text-slate">{description}</p>
      </div>
    </button>
  );
}

function QuickServiceCard({ icon: Icon, title, hint, onClick, highlight = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'group flex items-center gap-3 rounded-2xl border p-3.5 text-left shadow-card transition-all duration-base ease-glide',
        'hover:-translate-y-0.5 hover:shadow-lift active:translate-y-0 active:scale-[0.99]',
        highlight
          ? 'border-mint-300 bg-mint-50/40 hover:bg-mint-50'
          : 'border-line/80 bg-canvas hover:border-mint-500/30 hover:bg-mist/30',
      )}
    >
      <span
        className={cx(
          'grid h-10 w-10 shrink-0 place-items-center rounded-xl text-slate transition-all duration-base ease-glide',
          highlight
            ? 'bg-mint text-ink'
            : 'bg-mist text-slate group-hover:bg-mint-50 group-hover:text-mint-700 group-hover:scale-105',
        )}
      >
        <Icon className="h-5 w-5" />
      </span>

      <div className="min-w-0 flex-1">
        <span className="block truncate text-xs font-bold text-ink">{title}</span>
        <span className="block truncate text-2xs text-slate group-hover:text-mint-800 transition-colors">
          {hint}
        </span>
      </div>

      <IconChevron className="h-4 w-4 shrink-0 text-slate-light transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
    </button>
  );
}

function SetupBanner({ icon, title, description, cta, onClick }) {
  return (
    <div className="flex flex-col items-start justify-between gap-3 rounded-2xl border border-mint-200 bg-mint-50/80 p-4 shadow-card sm:flex-row sm:items-center sm:gap-4 sm:p-5">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mint text-ink shadow-sm">
          {icon}
        </span>
        <div>
          <p className="text-sm font-bold text-ink">{title}</p>
          <p className="text-xs text-mint-900/80">{description}</p>
        </div>
      </div>

      <Button
        variant="primary"
        size="sm"
        onClick={onClick}
        className="shrink-0 rounded-xl bg-ink text-white hover:bg-ink-800"
      >
        {cta}
      </Button>
    </div>
  );
}

function HubSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-7 pb-6 sm:space-y-9">
      <Skeleton className="h-28 rounded-3xl" />
      <div className="grid gap-5 lg:grid-cols-12">
        <Skeleton className="h-64 rounded-3xl lg:col-span-8" />
        <Skeleton className="h-64 rounded-3xl lg:col-span-4" />
      </div>
      <Skeleton className="h-28 rounded-3xl" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-28 rounded-2xl" />
        <Skeleton className="h-28 rounded-2xl" />
        <Skeleton className="h-28 rounded-2xl" />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-40 rounded-2xl" />
        <Skeleton className="h-40 rounded-2xl" />
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    </div>
  );
}

function timeGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}
