import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Row, Skeleton } from '../../components/ui';
import { CreditCardFace } from '../../components/credit/CreditCardFace';
import {
  ErrorCard, JourneySteps, StatusHero, friendlyError,
} from '../../components/credit/CreditUI';
import { useToast } from '../../context/ToastContext';
import { useReturnTo } from '../../hooks/useNavHistory';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

/**
 * Activation: the last step before the card can be used.
 *
 * Shows the card as it will look, because this is the first time the holder sees
 * it and the moment the product becomes real to them. The number on the face is
 * the masked one the server returns - the middle digits are not stored anywhere,
 * so there is nothing here that could leak them even by accident.
 *
 * Success is shown here, in place, rather than by jumping away: the holder gets
 * a moment that says "done", and the way onward goes back to the card screen
 * that is already in their history instead of stacking a second copy of it.
 */

export default function CreditActivate() {
  const navigate = useNavigate();
  const returnTo = useReturnTo();
  const toast = useToast();

  const { data: account, loading, error, refetch, setData } = useFetch(
    () => endpoints.credit.account(), [],
  );
  const [busy, setBusy] = useState(false);
  const [justActivated, setJustActivated] = useState(false);

  async function activate() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await endpoints.credit.activate();
      setData(response.data);
      setJustActivated(true);
    } catch (err) {
      toast.error(friendlyError(err, 'We could not activate your card. Please try again.'));
      // Re-read rather than assume: the refusal may be because the purpose is
      // still missing, and what this screen shows depends on which state it is.
      refetch();
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Activate your card" back="/credit" />
        <Skeleton className="h-56 w-full rounded-3xl" />
        <Skeleton className="mt-4 h-40 w-full rounded-2xl" />
      </div>
    );
  }

  if (!account) {
    const noLine = error?.code === 'NO_CREDIT_LINE' || error?.status === 404;
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Activate your card" back="/credit" />
        {noLine ? (
          <Card className="p-6 text-center">
            <p className="text-sm text-slate">You do not have a credit card yet.</p>
            <Button variant="mint" size="lg" full className="mt-4" onClick={() => navigate('/credit/apply')}>
              Apply for a credit card
            </Button>
          </Card>
        ) : (
          <ErrorCard error={error} title="We could not load your card" onRetry={refetch} />
        )}
      </div>
    );
  }

  if (account.status === 'ACTIVE') {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title={justActivated ? '' : 'Your card is active'} back="/credit" />

        {justActivated && <JourneySteps current="ACTIVE" className="mb-5" />}

        <Card className="p-6 sm:p-8">
          <StatusHero
            kind="success"
            title={justActivated ? 'Your card is active' : 'Already active'}
            subtitle={`${money(account.available_credit)} is ready to use.`}
          />
          <div className="mt-6">
            <CreditCardFace account={account} />
          </div>
          <div className="mt-6 space-y-2">
            <Button variant="mint" size="lg" full onClick={() => returnTo('/credit')}>
              Go to my card
            </Button>
            <Button variant="ghost" size="lg" full onClick={() => navigate('/credit/spend', { replace: true })}>
              Make a payment
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (account.status === 'PENDING_PURPOSE') {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="One step first" back="/credit" />
        <JourneySteps current="PURPOSE" className="mb-5" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">Tell us what this credit is for</p>
          <p className="mt-1 text-sm text-slate">We need this before the card can be activated.</p>
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-5"
            onClick={() => navigate('/credit/purpose', { replace: true })}
          >
            Choose a purpose
          </Button>
        </Card>
      </div>
    );
  }

  if (account.status !== 'PENDING_ACTIVATION') {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Activate your card" back="/credit" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">This card cannot be activated</p>
          <p className="mt-1 text-sm text-slate">
            {account.status === 'BLOCKED' ? 'It is frozen. Unfreeze it from your card screen.' : 'Contact support if you think this is a mistake.'}
          </p>
          <Button variant="outline" size="lg" full className="mt-5" onClick={() => returnTo('/credit')}>
            Go to my card
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader
        eyebrow="Final step"
        title="Activate your card"
        subtitle="Everything is ready. One tap and you can start using it."
        back="/credit"
      />

      <JourneySteps current="ACTIVE" className="mb-5" />

      <div className="mb-5">
        <CreditCardFace account={account} />
      </div>

      <Card className="mb-4 divide-y divide-line py-1">
        <Row label="Credit limit" value={money(account.credit_limit)} mono />
        <Row label="Available to spend" value={money(account.available_credit)} mono />
        <Row label="Purpose" value={account.purpose_label} />
        {account.purpose_note && <Row label="Your note" value={account.purpose_note} />}
        <Row label="Statement date" value={`${account.statement_day} of each month`} />
        <Row label="Payment window" value={`${account.grace_days} days after the statement`} />
      </Card>

      <Button variant="mint" size="lg" full loading={busy} onClick={activate}>
        Activate my card
      </Button>

      <p className="mt-3 text-center text-2xs leading-relaxed text-slate">
        You can freeze the card at any time, and nothing is charged until you use it.
      </p>
    </div>
  );
}
