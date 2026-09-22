import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardTile, DueItem, EmiRow, TransactionRow } from '../../components/domain';
import {
  IconBank, IconEmi, IconPlus, IconTransfer, PageHeader,
} from '../../components/layout/AppShell';
import {
  AnimatedMoney, Button, Card, EmptyState, Section, Skeleton, cx,
} from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { Reveal } from '../../hooks/useReveal';
import { money, moneyCompact } from '../../utils/format';

/**
 * Dashboard (PRD FR-002).
 *
 * The brief asks for an "immediate, anxiety-free assessment" of what the user
 * owes. On a desktop that means the whole picture in one view without scrolling
 * for it: the debt summary and the nearest payment sit side by side above the
 * fold, with cards, EMIs and activity arranged in columns beneath.
 */
export default function Home() {
  const navigate = useNavigate();
  const { data, loading, error } = useFetch(() => endpoints.dashboard.get(), []);

  if (loading) return <HomeSkeleton />;

  if (error) {
    return (
      <EmptyState
        title="We could not load your dashboard"
        description={error.message}
        action={
          <Button variant="outline" onClick={() => window.location.reload()}>
            Try again
          </Button>
        }
      />
    );
  }

  const summary = data.summary;
  const badge = summary.utilization_badge;

  return (
    <div className="animate-fade-up">
      <PageHeader
        title="Dashboard"
        subtitle="Everything you owe, in one place."
        action={
          <div className="flex gap-2">
            <Button variant="outline" size="md" onClick={() => navigate('/cards/add')}>
              <IconPlus className="h-4 w-4" />
              Add card
            </Button>
            <Button
              variant="mint"
              size="md"
              disabled={!data.quick_actions.can_transfer}
              onClick={() => navigate('/transfer')}
            >
              <IconTransfer className="h-4 w-4" />
              Transfer to bank
            </Button>
          </div>
        }
      />

      {/* ── Setup prompts ───────────────────────────────────────────── */}
      {data.quick_actions.needs_kyc && (
        <SetupPrompt
          title="Verify your identity"
          description="Complete KYC to link cards and move money."
          cta="Verify now"
          onClick={() => navigate('/kyc')}
        />
      )}

      {!data.quick_actions.needs_kyc && data.quick_actions.needs_bank_account && (
        <SetupPrompt
          title="Add your bank account"
          description="Verify an account so transfers have somewhere to land."
          cta="Add account"
          onClick={() => navigate('/banks/add')}
        />
      )}

      {/* ── Top row: debt summary + next payment ────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-3">
        <section className="relative overflow-hidden rounded-2xl bg-ink p-6 text-white shadow-lift lg:col-span-2">
          {/* The same treatment CardTile uses: a hairline along the top edge and
              one soft corner bloom. It stops a flat ink panel reading as a plain
              rectangle without tipping into skeuomorphism. Both are aria-hidden
              and pointer-events-none, so nothing here is reachable or readable. */}
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/15"
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full bg-mint/10 blur-3xl"
          />

          <div className="relative flex flex-wrap items-start justify-between gap-6">
            <div>
              <p className="text-xs text-white/55">Total outstanding</p>
              <AnimatedMoney
                value={summary.total_debt}
                format={(v) => money(v)}
                className="mt-1.5 block text-[2.5rem] font-bold leading-none tracking-tight"
              />
              <p className="mt-2 text-xs text-white/50">
                across {data.counts.cards} card{data.counts.cards === 1 ? '' : 's'} and{' '}
                {data.counts.emi_obligations} loan
                {data.counts.emi_obligations === 1 ? '' : 's'}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-2xs text-white/50">Available credit</p>
                <p className="money mt-1 text-xl font-bold text-mint">
                  {money(summary.total_available_credit)}
                </p>
              </div>
              <div>
                <p className="text-2xs text-white/50">Aggregate limit</p>
                <p className="money mt-1 text-xl font-semibold text-white/85">
                  {moneyCompact(summary.total_credit_limit)}
                </p>
              </div>
            </div>
          </div>

          {summary.credit_utilization_percentage !== null && (
            <div className="relative mt-6 border-t border-white/10 pt-4">
              <div className="flex items-center justify-between">
                <span className="text-2xs text-white/55">Credit utilisation</span>
                <span
                  className={cx(
                    'rounded-full px-2.5 py-0.5 text-2xs font-semibold',
                    badge.tone === 'good' && 'bg-mint text-ink',
                    badge.tone === 'neutral' && 'bg-white/15 text-white',
                    badge.tone === 'warn' && 'bg-warn text-ink',
                    badge.tone === 'alert' && 'bg-alert text-white',
                  )}
                >
                  {summary.credit_utilization_percentage}% · {badge.label}
                </span>
              </div>

              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white/15">
                <div
                  className={cx(
                    'h-full rounded-full transition-all duration-700',
                    badge.tone === 'good' && 'bg-mint',
                    badge.tone === 'neutral' && 'bg-white/70',
                    badge.tone === 'warn' && 'bg-warn',
                    badge.tone === 'alert' && 'bg-alert',
                  )}
                  style={{ width: `${Math.min(100, summary.credit_utilization_percentage)}%` }}
                />
              </div>

              <p className="mt-2 text-2xs text-white/40">
                Keeping utilisation under 30% helps your credit score.
              </p>
            </div>
          )}
        </section>

        {/* Next payment */}
        <div className="lg:col-span-1">
          {data.next_due_item ? (
            <NextDueCard
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
            <Card className="flex h-full flex-col justify-center border-dashed text-center">
              <p className="text-sm font-semibold text-ink">Nothing due</p>
              <p className="mt-1 text-xs text-slate">
                No payments in the next 30 days.
              </p>
            </Card>
          )}
        </div>
      </div>

      {/* ── Monthly commitment strip ────────────────────────────────── */}
      {summary.monthly_emi_commitment > 0 && (
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {[
            ['Monthly EMI commitment', summary.monthly_emi_commitment],
            ['EMI outstanding', summary.emi_outstanding],
            ['Card outstanding', summary.total_outstanding_amount],
          ].map(([label, value], index) => (
            <Reveal key={label} delay={index * 70} className="h-full">
              <StatStrip label={label} value={money(value)} />
            </Reveal>
          ))}
        </div>
      )}

      {/* ── Upcoming dues ───────────────────────────────────────────── */}
      {data.upcoming_dues?.length > 1 && (
        <Section title="Upcoming payments" className="mt-8">
          <div className="grid gap-2 lg:grid-cols-2">
            {data.upcoming_dues.map((item, index) => (
              <Reveal
                key={`${item.type}-${item.id}`}
                // Capped so a long list never leaves the last row waiting; past
                // the sixth item the delay stops growing and they arrive together.
                delay={Math.min(index, 5) * 60}
                className="h-full [&>*]:h-full"
              >
                <DueItem
                  item={item}
                  onClick={() =>
                    navigate(item.type === 'EMI' ? `/emi/${item.id}` : `/cards/${item.id}`)
                  }
                />
              </Reveal>
            ))}
          </div>
        </Section>
      )}

      {/* ── Cards ───────────────────────────────────────────────────── */}
      <Section
        title="Your cards"
        className="mt-8"
        action={
          data.cards.length > 0 && (
            <button
              type="button"
              onClick={() => navigate('/cards')}
              className="text-xs font-semibold text-mint-700"
            >
              Manage cards
            </button>
          )
        }
      >
        {data.cards.length === 0 ? (
          <Card className="border-dashed">
            <EmptyState
              title="No cards linked"
              description="Add a credit card to track limits, due dates and utilisation."
              action={
                <Button variant="mint" size="sm" onClick={() => navigate('/cards/add')}>
                  Add your first card
                </Button>
              }
              className="py-6"
            />
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.cards.map((card, index) => (
              <Reveal key={card.card_id} delay={Math.min(index, 5) * 60} className="h-full [&>*]:h-full">
                <CardTile card={card} onClick={() => navigate(`/cards/${card.card_id}`)} />
              </Reveal>
            ))}

            <Reveal delay={Math.min(data.cards.length, 6) * 60} className="h-full [&>*]:h-full">
              <button
                type="button"
                onClick={() => navigate('/cards/add')}
                className="group grid h-full min-h-[156px] w-full place-items-center rounded-2xl border-2 border-dashed border-line text-slate transition-all duration-base ease-glide hover:border-mint-600/40 hover:bg-mint-50/40 hover:text-ink active:scale-[0.985]"
              >
                <span className="flex flex-col items-center gap-2">
                  <IconPlus className="h-5 w-5 transition-transform duration-base ease-glide group-hover:scale-110" />
                  <span className="text-sm font-medium">Add card</span>
                </span>
              </button>
            </Reveal>
          </div>
        )}
      </Section>

      {/* ── EMIs + activity, side by side ───────────────────────────── */}
      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <Reveal>
        <Section
          title="Active EMIs"
          action={
            data.emi_obligations.length > 0 && (
              <button
                type="button"
                onClick={() => navigate('/emi')}
                className="text-xs font-semibold text-mint-700"
              >
                See all
              </button>
            )
          }
        >
          {data.emi_obligations.length === 0 ? (
            <Card className="border-dashed">
              <EmptyState
                icon={<IconEmi className="h-6 w-6" />}
                title="No EMIs tracked"
                description="Add a loan to see every due date in one calendar."
                action={
                  <Button variant="outline" size="sm" onClick={() => navigate('/emi/add')}>
                    Add an EMI
                  </Button>
                }
                className="py-5"
              />
            </Card>
          ) : (
            <div className="space-y-2">
              {data.emi_obligations.slice(0, 4).map((emi) => (
                <EmiRow
                  key={emi.emi_id}
                  emi={emi}
                  onClick={() => navigate(`/emi/${emi.emi_id}`)}
                />
              ))}
            </div>
          )}
        </Section>
        </Reveal>

        <Reveal delay={90}>
        <Section
          title="Recent activity"
          action={
            data.recent_transactions.length > 0 && (
              <button
                type="button"
                onClick={() => navigate('/transactions')}
                className="text-xs font-semibold text-mint-700"
              >
                View all
              </button>
            )
          }
        >
          {data.recent_transactions.length === 0 ? (
            <Card className="border-dashed">
              <EmptyState
                icon={<IconBank className="h-6 w-6" />}
                title="No activity yet"
                description="Your transfers and EMI payments will appear here."
                className="py-5"
              />
            </Card>
          ) : (
            <Card className="divide-y divide-line py-0">
              {data.recent_transactions.map((transaction) => (
                <TransactionRow
                  key={transaction.transaction_id}
                  transaction={transaction}
                  onClick={() => navigate(`/transactions/${transaction.transaction_id}`)}
                />
              ))}
            </Card>
          )}
        </Section>
        </Reveal>
      </div>
    </div>
  );
}

/* ── Pieces ─────────────────────────────────────────────────────────────── */

function StatStrip({ label, value }) {
  return (
    // h-full so the three strips stay level once each is wrapped in its own
    // reveal; shadow-card for depth, but no hover lift - nothing here is
    // clickable, and a tile that rises under the cursor promises otherwise.
    <div className="h-full rounded-2xl border border-line bg-canvas p-4 shadow-card">
      <p className="text-2xs font-semibold uppercase tracking-wider text-slate">{label}</p>
      <p className="money mt-1.5 text-xl font-bold text-ink">{value}</p>
    </div>
  );
}

function NextDueCard({ item, onPay }) {
  const overdue = item.is_overdue;
  const urgent = !overdue && item.days_remaining <= 3;

  return (
    <section
      className={cx(
        'flex h-full flex-col rounded-2xl border p-5 shadow-card',
        overdue
          ? 'border-alert/30 bg-red-50/40'
          : urgent
            ? 'border-warn/30 bg-amber-50/40'
            : 'border-line bg-canvas',
      )}
    >
      <p
        className={cx(
          'text-2xs font-semibold uppercase tracking-wider',
          overdue ? 'text-alert' : urgent ? 'text-warn' : 'text-slate',
        )}
      >
        {overdue ? 'Overdue' : urgent ? 'Due soon' : 'Next payment'}
      </p>

      <p className="mt-2 truncate text-sm font-semibold text-ink">{item.title}</p>
      <p className="truncate text-xs text-slate">{item.subtitle}</p>

      <p className="money mt-4 text-3xl font-bold leading-none text-ink">
        {money(item.amount)}
      </p>

      <p className="mt-1.5 text-xs text-slate">
        {overdue
          ? `${Math.abs(item.days_remaining)} days late`
          : item.days_remaining === 0
            ? 'Due today'
            : `Due in ${item.days_remaining} days`}
      </p>

      {item.minimum_due ? (
        <p className="mt-1 text-2xs text-slate">
          Minimum due{' '}
          <span className="money font-medium text-ink">{money(item.minimum_due)}</span>
        </p>
      ) : null}

      <div className="mt-auto pt-5">
        <Button variant="mint" size="md" full onClick={onPay}>
          {item.type === 'EMI' ? 'Pay EMI now' : 'View card'}
        </Button>
      </div>
    </section>
  );
}

function SetupPrompt({ title, description, cta, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group mb-4 flex w-full items-center gap-3 rounded-2xl border border-mint-200 bg-mint-50 p-4 text-left transition-all duration-base ease-glide hover:-translate-y-0.5 hover:border-mint-300 hover:shadow-lift active:translate-y-0 active:scale-[0.995]"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mint text-ink transition-transform duration-base ease-glide group-hover:scale-105">
        <IconPlus className="h-5 w-5" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="truncate text-xs text-mint-800/70">{description}</p>
      </div>

      <span className="shrink-0 rounded-lg bg-ink px-3 py-1.5 text-xs font-semibold text-white transition-colors duration-base ease-glide group-hover:bg-ink-700">
        {cta}
      </span>
    </button>
  );
}

function HomeSkeleton() {
  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-7 w-40" />
          <Skeleton className="h-4 w-56" />
        </div>
        <Skeleton className="h-11 w-44 rounded-xl" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-56 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-56 rounded-2xl" />
      </div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-[156px] rounded-2xl" />
        ))}
      </div>
    </div>
  );
}
