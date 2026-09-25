import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Row, Skeleton } from '../../components/ui';
import { CreditCardFace } from '../../components/credit/CreditCardFace';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

/**
 * Activation: the last step before the line can be spent.
 *
 * Shows the card as it will look, because this is the first time the holder sees
 * it and the moment the product becomes real to them. The number on the face is
 * the masked one the server returns - the middle digits are not stored anywhere,
 * so there is nothing here that could leak them even by accident.
 */

export default function CreditActivate() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: account, loading, refetch } = useFetch(
    () => endpoints.credit.account(), [],
  );
  const [busy, setBusy] = useState(false);

  async function activate() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await endpoints.credit.activate();
      toast.success(response.message || 'Your card is active.');
      navigate('/credit', { replace: true });
    } catch (error) {
      toast.error(error?.message || 'We could not activate your card.');
      // Re-read rather than assume: the refusal may be because the purpose is
      // still missing, and the next screen depends on which state it is in.
      refetch();
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Activate your card" back />
        <Card><Skeleton className="h-56 w-full" /></Card>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Activate your card" back />
        <Card className="text-center">
          <p className="text-sm text-slate">You do not have a credit line yet.</p>
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-4"
            onClick={() => navigate('/credit/apply')}
          >
            Apply for credit
          </Button>
        </Card>
      </div>
    );
  }

  // Already live. Sending them to the card beats an activation screen for
  // something that is already activated.
  if (account.status === 'ACTIVE') {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Your card is active" back="/credit" />
        <Card className="text-center">
          <p className="text-sm text-slate">
            This card is already active and ready to use.
          </p>
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-4"
            onClick={() => navigate('/credit', { replace: true })}
          >
            View my card
          </Button>
        </Card>
      </div>
    );
  }

  if (account.status === 'PENDING_PURPOSE') {
    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="One step first" back />
        <Card className="text-center">
          <p className="text-base font-semibold text-ink">
            Tell us what this credit is for
          </p>
          <p className="mt-1 text-sm text-slate">
            We need this before the card can be activated.
          </p>
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

  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader
        title="Activate your card"
        subtitle="Everything is ready. One tap and you can start using it."
        back
      />

      <div className="mb-5">
        <CreditCardFace account={account} />
      </div>

      <Card className="mb-4">
        <Row label="Credit limit" value={money(account.credit_limit)} mono />
        <Row label="Available to spend" value={money(account.available_credit)} mono />
        <Row label="Purpose" value={account.purpose_label} />
        {account.purpose_note && (
          <Row label="Your note" value={account.purpose_note} />
        )}
        <Row
          label="Statement date"
          value={`${account.statement_day} of each month`}
        />
        <Row label="Payment window" value={`${account.grace_days} days after`} />
      </Card>

      <Button variant="mint" size="lg" full loading={busy} onClick={activate}>
        Activate my card
      </Button>

      <p className="mt-3 text-center text-2xs leading-relaxed text-slate">
        You can freeze the card at any time from your card settings, and nothing
        is charged until you spend.
      </p>
    </div>
  );
}
