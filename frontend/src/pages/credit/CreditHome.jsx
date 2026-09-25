import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { ListLink } from '../../components/domain';
import {
  Badge, Button, Card, EmptyState, Section, Sheet, Skeleton,
} from '../../components/ui';
import { CreditCardFace } from '../../components/credit/CreditCardFace';
import { CreditTransactionRow } from '../../components/credit/CreditTransactionRow';
import {
  ActionTile, CreditBalances, ErrorCard, GLYPHS, Glyph, JourneySteps,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * The credit line's home.
 *
 * Routes by state rather than showing one screen with disabled parts: somebody
 * who has not applied, somebody waiting on a decision and somebody holding an
 * active card need different screens, not the same screen with different things
 * greyed out.
 *
 * `next_step` comes from the server, so the order of the journey is decided in
 * one place. This screen asks what to do next rather than inferring it from the
 * status, which means a change to the sequence does not need a frontend change
 * to match.
 */

export default function CreditHome() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: account, loading, error, refetch } = useFetch(
    () => endpoints.credit.account(), [],
  );
  const { data: eligibility } = useFetch(
    () => endpoints.credit.eligibility(), [],
  );
  const { data: current, refetch: refetchCurrent } = useFetch(
    () => endpoints.credit.currentStatement(), [account?.credit_account_id],
    { skip: !account },
  );
  const { data: history } = useFetch(
    () => endpoints.credit.transactions(1), [account?.credit_account_id],
    { skip: !account },
  );

  const [freezeOpen, setFreezeOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggleFreeze() {
    setBusy(true);
    try {
      if (account.status === 'BLOCKED') {
        await endpoints.credit.unblock();
        toast.success('Card unfrozen. You can use it again.');
      } else {
        await endpoints.credit.block('Frozen by cardholder');
        toast.success('Card frozen. Nothing can be spent on it.');
      }
      setFreezeOpen(false);
      refetch();
      refetchCurrent();
    } catch (err) {
      toast.error(err?.message || 'We could not change that. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Credit card" back="/home" />
        <Skeleton className="h-56 w-full rounded-3xl" />
        <Skeleton className="mt-4 h-28 w-full rounded-2xl" />
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  /* ── No credit line ─────────────────────────────────────────────────── */
  // A 404 here is the documented "you have no card" answer, not a failure. Any
  // other error is a real one and says so, because telling somebody they have
  // no card when the request simply failed would be a lie.
  if (!account) {
    const noLine = error?.code === 'NO_CREDIT_LINE' || error?.status === 404;

    if (!noLine && error) {
      return (
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader title="Credit card" back="/home" />
          <ErrorCard
            error={error}
            title="We could not load your credit card"
            onRetry={refetch}
          />
        </div>
      );
    }

    const openApplication = eligibility?.open_application_id;

    return (
      <div className="mx-auto w-full max-w-3xl animate-fade-up">
        <PageHeader
          eyebrow="CashU Credit"
          title="Credit card"
          subtitle="A credit card, decided on what you earn."
          back="/home"
        />

        <JourneySteps current={openApplication ? 'REVIEW' : 'APPLY'} className="mb-5" />

        {openApplication ? (
          <Card className="p-6 text-center">
            <Badge tone="warn" dot>Application in progress</Badge>
            <p className="mt-3 text-lg font-semibold text-ink">
              Your application is with us
            </p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-slate">
              We will let you know as soon as there is a decision. Nothing more is
              needed from you unless the status says so.
            </p>
            <Button
              variant="mint"
              size="lg"
              full
              className="mt-5"
              onClick={() => navigate(`/credit/status/${openApplication}`)}
            >
              Check the status
            </Button>
          </Card>
        ) : (
          <Card className="overflow-hidden !p-0">
            <div className="relative bg-gradient-to-br from-ink via-[#0f1a1f] to-[#062019] px-6 py-8 text-center text-white">
              <span
                aria-hidden="true"
                className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-mint/25 blur-3xl"
              />
              <p className="relative text-2xs font-semibold uppercase tracking-[0.18em] text-mint-300">
                CashU Credit Card
              </p>
              <p className="relative mt-2 text-2xl font-bold tracking-tight">
                Spend now. Pay by your due date.
              </p>
              {eligibility?.max_limit_for_tier > 0 && (
                <p className="relative mt-2 text-sm text-white/70">
                  Limits up to{' '}
                  <span className="money font-semibold text-white">
                    {money(eligibility.max_limit_for_tier, { decimals: 0 })}
                  </span>{' '}
                  for your KYC level
                </p>
              )}
            </div>

            <div className="p-5 sm:p-6">
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { title: 'Decided fast', body: 'Usually within one working day.' },
                  { title: 'No hidden fees', body: 'A late fee only if you miss the minimum due.' },
                  { title: 'Pay any way', body: 'UPI, net banking or debit card.' },
                ].map((item) => (
                  <div key={item.title} className="rounded-xl border border-line bg-mist/40 p-3.5">
                    <p className="text-sm font-medium text-ink">{item.title}</p>
                    <p className="mt-0.5 text-2xs leading-relaxed text-slate">{item.body}</p>
                  </div>
                ))}
              </div>

              {eligibility?.kyc_required && (
                <p className="mt-4 rounded-xl bg-amber-50 px-3.5 py-3 text-xs text-amber-800">
                  You can apply now. We will ask you to complete KYC before your
                  application is decided.
                </p>
              )}

              <Button
                variant="mint"
                size="lg"
                full
                className="mt-5"
                onClick={() => navigate('/credit/apply')}
              >
                Apply for a credit card
              </Button>
            </div>
          </Card>
        )}
      </div>
    );
  }

  /* ── Issued, but not yet usable ─────────────────────────────────────── */
  const nextStep = account.next_step;

  if (nextStep === 'DECLARE_PURPOSE' || nextStep === 'ACTIVATE') {
    const purposeNext = nextStep === 'DECLARE_PURPOSE';

    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader
          eyebrow="Approved"
          title="Almost there"
          subtitle={`Your ${money(account.credit_limit, { decimals: 0 })} limit is approved.`}
          back="/home"
        />

        <JourneySteps current={purposeNext ? 'PURPOSE' : 'ACTIVE'} className="mb-5" />

        <div className="mb-5">
          <CreditCardFace account={account} />
        </div>

        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">
            {purposeNext ? 'Tell us what this credit is for' : 'Activate your card'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {purposeNext
              ? 'One question, and it is required before the card can be used.'
              : 'Everything is ready. One tap and you can start using it.'}
          </p>
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-5"
            onClick={() => navigate(purposeNext ? '/credit/purpose' : '/credit/activate')}
          >
            {purposeNext ? 'Choose a purpose' : 'Activate now'}
          </Button>
        </Card>
      </div>
    );
  }

  /* ── Active (or frozen) ─────────────────────────────────────────────── */
  const statement = current?.latest_statement;
  const pending = current?.pending_payment;
  const frozen = account.status === 'BLOCKED';
  const outstanding = Number(account.current_outstanding || 0);
  const transactions = history || [];
  const owesOnStatement = statement && statement.amount_outstanding > 0;

  return (
    <div className="mx-auto w-full max-w-3xl animate-fade-up">
      <PageHeader
        eyebrow="CashU Credit"
        title="Credit card"
        // "For other" says nothing; the holder's own words say what it is for.
        subtitle={
          account.purpose === 'OTHER' && account.purpose_note
            ? `For ${account.purpose_note}`
            : account.purpose_label ? `For ${account.purpose_label.toLowerCase()}` : null
        }
        back="/home"
        action={frozen ? <Badge tone="alert" dot>Frozen</Badge> : <Badge tone="good" dot>Active</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
        <div className="space-y-4">
          <CreditCardFace account={account} />
          <CreditBalances account={account} />
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <ActionTile
              primary
              icon={<Glyph d={GLYPHS.spend} />}
              label="Pay with card"
              hint={frozen ? 'Card is frozen' : `${money(account.available_credit, { decimals: 0 })} available`}
              disabled={frozen}
              onClick={() => navigate('/credit/spend')}
            />
            <ActionTile
              icon={<Glyph d={GLYPHS.bill} />}
              label="Pay bill"
              hint={outstanding > 0 ? `${money(outstanding, { decimals: 0 })} owed` : 'Nothing owed'}
              onClick={() => navigate('/credit/pay')}
            />
            <ActionTile
              icon={<Glyph d={GLYPHS.statement} />}
              label="Statements"
              hint="Monthly bills"
              onClick={() => navigate('/credit/statements')}
            />
            <ActionTile
              icon={<Glyph d={GLYPHS.activity} />}
              label="Transactions"
              hint="Everything on this card"
              onClick={() => navigate('/credit/transactions')}
            />
          </div>

          {/* A payment still with the gateway. Surfaced here so nobody pays
              again because they think the first one vanished. */}
          {pending && (
            <Card
              className="border-amber-200 bg-amber-50/60"
              onClick={() => navigate(`/credit/transactions/${pending.credit_transaction_id}`)}
            >
              <div className="flex items-start gap-3">
                <span className="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full bg-warn" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink">
                    Payment of {money(pending.amount)} is processing
                  </p>
                  <p className="mt-0.5 text-xs text-slate">
                    Your credit is restored as soon as your bank confirms it. Do
                    not pay again.
                  </p>
                </div>
              </div>
            </Card>
          )}

          {/* What is owed and by when. The most actionable card on the screen. */}
          {owesOnStatement ? (
            <Card className="border-mint-600/30">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                    Statement due {date(statement.due_date)}
                  </p>
                  <p className="money mt-1 text-3xl font-bold text-ink">
                    {money(statement.amount_outstanding)}
                  </p>
                  {statement.minimum_outstanding > 0 && (
                    <p className="mt-1 text-xs text-slate">
                      Minimum due{' '}
                      <span className="money font-medium text-ink">
                        {money(statement.minimum_outstanding)}
                      </span>
                    </p>
                  )}
                </div>
                <Badge tone={statement.status === 'OVERDUE' ? 'alert' : 'warn'} dot>
                  {statement.status.replace(/_/g, ' ')}
                </Badge>
              </div>
              <Button
                variant="mint"
                size="lg"
                full
                className="mt-4"
                disabled={Boolean(pending)}
                onClick={() => navigate('/credit/pay')}
              >
                Pay bill
              </Button>
            </Card>
          ) : outstanding > 0 && (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                    Spent since your last statement
                  </p>
                  <p className="money mt-1 text-2xl font-bold text-ink">
                    {money(outstanding)}
                  </p>
                  <p className="mt-0.5 text-2xs text-slate">
                    Pay any time before your statement to free up credit now.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="md"
                  disabled={Boolean(pending)}
                  onClick={() => navigate('/credit/pay')}
                >
                  Pay now
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>

      <Section
        className="mt-6"
        title="Recent transactions"
        action={
          transactions.length > 0 && (
            <button
              type="button"
              onClick={() => navigate('/credit/transactions')}
              className="text-xs font-semibold text-mint-700 transition hover:text-mint-800"
            >
              See all
            </button>
          )
        }
      >
        {transactions.length === 0 ? (
          <Card>
            <EmptyState
              className="py-8"
              title="No transactions yet"
              description="Payments you make with this card will appear here."
              action={!frozen && (
                <Button variant="mint" size="md" onClick={() => navigate('/credit/spend')}>
                  Make your first payment
                </Button>
              )}
            />
          </Card>
        ) : (
          <Card className="py-1">
            <div className="divide-y divide-line">
              {transactions.slice(0, 5).map((txn) => (
                <CreditTransactionRow
                  key={txn.credit_transaction_id}
                  transaction={txn}
                  showBalance={false}
                  onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
                />
              ))}
            </div>
          </Card>
        )}
      </Section>

      <Section title="Manage" className="mt-6">
        <Card className="py-1">
          <div className="divide-y divide-line">
            <ListLink
              label={frozen ? 'Unfreeze card' : 'Freeze card'}
              description={frozen ? 'Allow payments on this card again' : 'Stop all payments immediately'}
              onClick={() => setFreezeOpen(true)}
              danger={!frozen}
            />
          </div>
        </Card>
      </Section>

      <Sheet
        open={freezeOpen}
        onClose={() => setFreezeOpen(false)}
        title={frozen ? 'Unfreeze this card?' : 'Freeze this card?'}
        footer={
          <div className="flex gap-2">
            <Button variant="outline" size="lg" full onClick={() => setFreezeOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={frozen ? 'mint' : 'danger'}
              size="lg"
              full
              loading={busy}
              onClick={toggleFreeze}
            >
              {frozen ? 'Unfreeze' : 'Freeze'}
            </Button>
          </div>
        }
      >
        <p className="text-sm leading-relaxed text-slate">
          {frozen
            ? 'Payments will work again straight away.'
            : 'Nothing can be spent on this card until you unfreeze it. Anything you already owe stays owed, and you can still pay your bill.'}
        </p>
      </Sheet>
    </div>
  );
}
