import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { ListLink, TransactionRow } from '../../components/domain';
import {
  Badge, Button, Card, EmptyState, Meter, Row, Section, Sheet, Skeleton,
} from '../../components/ui';
import { CreditCardFace } from '../../components/credit/CreditCardFace';
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
  const { data: current } = useFetch(
    () => endpoints.credit.currentStatement(), [], { skip: !account },
  );
  const { data: history } = useFetch(
    () => endpoints.credit.transactions(1), [], { skip: !account },
  );

  const [freezeOpen, setFreezeOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggleFreeze() {
    setBusy(true);
    try {
      if (account.status === 'BLOCKED') {
        await endpoints.credit.unblock();
        toast.success('Card unfrozen.');
      } else {
        await endpoints.credit.block('Frozen by cardholder');
        toast.success('Card frozen. Nothing can be spent on it.');
      }
      setFreezeOpen(false);
      refetch();
    } catch (err) {
      toast.error(err?.message || 'We could not change that.');
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Credit" />
        <Skeleton className="h-52 w-full rounded-2xl" />
        <Card className="mt-4"><Skeleton className="h-32 w-full" /></Card>
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
          <PageHeader title="Credit" />
          <Card className="text-center">
            <p className="text-sm font-medium text-ink">
              We could not load your credit line
            </p>
            <p className="mt-1 text-xs text-slate">{error.message}</p>
            <Button variant="outline" size="md" className="mt-4" onClick={refetch}>
              Try again
            </Button>
          </Card>
        </div>
      );
    }

    const openApplication = eligibility?.open_application_id;

    return (
      <div className="mx-auto w-full max-w-3xl animate-fade-up">
        <PageHeader title="Credit" subtitle="A credit line, on your terms." />

        {openApplication ? (
          <Card className="text-center">
            <Badge tone="warn" dot>In progress</Badge>
            <p className="mt-3 text-base font-semibold text-ink">
              Your application is with us
            </p>
            <p className="mt-1 text-sm text-slate">
              We will let you know as soon as there is a decision.
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
          <Card>
            <div className="text-center">
              <p className="text-lg font-bold tracking-tight text-ink">
                Apply for a CashU credit line
              </p>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate">
                Spend now, pay by your statement date. A limit decided from what
                you earn, not from what you gamble on.
              </p>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              {[
                { title: 'Decided fast', body: 'Usually within one working day.' },
                { title: 'No hidden fees', body: 'Interest only if you pay late.' },
                { title: 'You choose the purpose', body: 'And we hold you to it.' },
              ].map((item) => (
                <div
                  key={item.title}
                  className="rounded-xl border border-line bg-mist/40 p-3.5"
                >
                  <p className="text-sm font-medium text-ink">{item.title}</p>
                  <p className="mt-0.5 text-2xs leading-relaxed text-slate">
                    {item.body}
                  </p>
                </div>
              ))}
            </div>

            {eligibility?.max_limit_for_tier > 0 && (
              <Row
                label="Maximum for your KYC level"
                value={money(eligibility.max_limit_for_tier)}
                mono
                className="mt-5"
              />
            )}

            <Button
              variant="mint"
              size="lg"
              full
              className="mt-5"
              onClick={() => navigate('/credit/apply')}
            >
              Apply now
            </Button>
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
          title="Almost there"
          subtitle={`Your ${money(account.credit_limit)} limit is approved.`}
        />

        <div className="mb-5">
          <CreditCardFace account={account} />
        </div>

        <Card className="text-center">
          <p className="text-base font-semibold text-ink">
            {purposeNext
              ? 'Tell us what this credit is for'
              : 'Activate your card'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {purposeNext
              ? 'One question, and it is required before the card can be used.'
              : 'Everything is ready. One tap and you can start spending.'}
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
  const frozen = account.status === 'BLOCKED';
  const utilization = account.utilization_percent || 0;
  const transactions = history || [];

  return (
    <div className="mx-auto w-full max-w-3xl animate-fade-up">
      <PageHeader
        title="Credit"
        subtitle={account.purpose_label ? `For ${account.purpose_label.toLowerCase()}` : null}
        action={frozen ? <Badge tone="alert" dot>Frozen</Badge> : null}
      />

      <div className="mb-5">
        <CreditCardFace account={account} />
      </div>

      {/* Utilization. Shown because a high balance is the thing most worth
          noticing on this screen, and a bar is read faster than a number. */}
      <Card className="mb-4">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <span className="text-sm text-slate">Used this cycle</span>
          <span className="money text-sm font-medium text-ink">
            {money(account.current_outstanding)} of {money(account.credit_limit)}
          </span>
        </div>
        <Meter
          value={utilization}
          tone={utilization > 80 ? 'alert' : utilization > 50 ? 'warn' : 'good'}
        />
        <p className="mt-2 text-2xs text-slate">
          {utilization > 80
            ? 'You are close to your limit. Paying some of this back frees it up.'
            : `${utilization}% of your limit is in use.`}
        </p>
      </Card>

      {/* What is owed and by when. The most actionable card on the screen, so
          it sits above everything else. */}
      {statement && statement.amount_outstanding > 0 && (
        <Card className="mb-4 border-mint-600/30">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                Due by {date(statement.due_date)}
              </p>
              <p className="money mt-1 text-3xl font-bold text-ink">
                {money(statement.amount_outstanding)}
              </p>
              {statement.minimum_outstanding > 0 && (
                <p className="mt-1 text-xs text-slate">
                  Minimum{' '}
                  <span className="money font-medium text-ink">
                    {money(statement.minimum_outstanding)}
                  </span>
                </p>
              )}
            </div>
            <Badge
              tone={statement.status === 'OVERDUE' ? 'alert' : 'warn'}
              dot
            >
              {statement.status.replace(/_/g, ' ')}
            </Badge>
          </div>

          <Button
            variant="mint"
            size="lg"
            full
            className="mt-4"
            onClick={() => navigate('/credit/pay')}
          >
            Pay now
          </Button>
        </Card>
      )}

      {current?.unbilled_spend > 0 && (
        <Row
          label="Spent since your last statement"
          value={money(current.unbilled_spend)}
          mono
          className="mb-4"
        />
      )}

      <Section
        title="Recent activity"
        action={
          transactions.length > 0 && (
            <button
              type="button"
              onClick={() => navigate('/credit/transactions')}
              className="text-xs font-medium text-mint-700 transition hover:text-mint-800"
            >
              See all
            </button>
          )
        }
      >
        {transactions.length === 0 ? (
          <EmptyState
            title="Nothing spent yet"
            description="Purchases on this card will appear here."
          />
        ) : (
          <Card className="py-1">
            <div className="divide-y divide-line">
              {transactions.slice(0, 5).map((txn) => (
                <TransactionRow
                  key={txn.credit_transaction_id}
                  transaction={{
                    transaction_id: txn.credit_transaction_id,
                    type: txn.type,
                    amount: txn.amount,
                    status: txn.status,
                    source: txn.merchant_name || txn.description,
                    created_on: txn.created_on,
                  }}
                  onClick={() => navigate(`/credit/transactions/${txn.credit_transaction_id}`)}
                />
              ))}
            </div>
          </Card>
        )}
      </Section>

      <Section title="Manage">
        <Card className="py-1">
          <div className="divide-y divide-line">
            <ListLink
              label="Statements"
              description="Monthly bills and receipts"
              onClick={() => navigate('/credit/statements')}
            />
            <ListLink
              label="All transactions"
              description="Everything on this card"
              onClick={() => navigate('/credit/transactions')}
            />
            <ListLink
              label={frozen ? 'Unfreeze card' : 'Freeze card'}
              description={
                frozen
                  ? 'Allow spending on this card again'
                  : 'Stop all spending immediately'
              }
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
            <Button
              variant="outline"
              size="lg"
              full
              onClick={() => setFreezeOpen(false)}
            >
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
            ? 'Spending will work again straight away.'
            : 'Nothing can be spent on this card until you unfreeze it. Anything you already owe stays owed, and you can still pay your bill.'}
        </p>
      </Sheet>
    </div>
  );
}
