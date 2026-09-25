import { useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { endpoints, newIdempotencyKey } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import { CreditCardFace } from '../../components/credit/CreditCardFace';
import {
  ErrorCard, MERCHANT_CATEGORIES, ProcessingPanel, categoryLabel, friendlyError,
  outcomeUnknown,
} from '../../components/credit/CreditUI';
import { useFetch } from '../../hooks/useProfile';
import { useSessionDraft } from '../../hooks/useSessionDraft';
import { money, sanitizeAmount } from '../../utils/format';

/**
 * Pay with the credit card.
 *
 * Purchases only - a merchant is named on every one, and there is no way to
 * send the credit line to a bank account from here or anywhere else.
 *
 * Two steps, and the step lives in the URL (?step=review) so the browser's own
 * back button moves between them exactly as the on-screen one does, with the
 * details still filled in.
 *
 * The idempotency key belongs to the *attempt*, not to the request. It is made
 * when the holder confirms and kept until the server gives a definite answer,
 * so a retry after a dropped connection replays the same purchase and cannot
 * charge twice. Changing any detail starts a new attempt with a new key.
 *
 * "Available after" on the review step is arithmetic for display only, and
 * labelled as such. The server decides; this screen cannot move a balance.
 */

const EMPTY = { merchant: '', amount: '', category: 'SHOPPING', note: '' };

export default function CreditSpend() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const reviewing = params.get('step') === 'review';

  const { data: account, loading, error: loadError, refetch } = useFetch(
    () => endpoints.credit.account(), [],
  );

  const [draft, update, clearDraft] = useSessionDraft('credit-spend', EMPTY);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [busy, setBusy] = useState(false);

  const attemptKey = useRef(null);
  const inFlight = useRef(false);

  const available = Number(account?.available_credit || 0);
  const amount = Number(draft.amount || 0);

  function edit(patch) {
    update(patch);
    // New details, new attempt: the old key named a different purchase.
    attemptKey.current = null;
    setSubmitError(null);
    setErrors({});
  }

  function validate() {
    const found = {};
    const merchant = draft.merchant.trim();

    if (merchant.length < 2) found.merchant = 'Enter who you are paying.';
    if (!draft.amount) found.amount = 'Enter an amount.';
    else if (!Number.isFinite(amount) || amount <= 0) found.amount = 'Enter a valid amount.';
    else if (amount > available) {
      found.amount = `Only ${money(available)} is available on your card.`;
    }
    setErrors(found);
    return Object.keys(found).length === 0;
  }

  function review() {
    if (!validate()) return;
    setParams({ step: 'review' });
  }

  async function pay() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setSubmitError(null);

    if (!attemptKey.current) attemptKey.current = newIdempotencyKey();

    try {
      const response = await endpoints.credit.purchase({
        amount: draft.amount,
        merchant_name: draft.merchant.trim(),
        merchant_category: draft.category,
        description: draft.note.trim() || undefined,
      }, attemptKey.current);

      attemptKey.current = null;
      clearDraft();
      // Replace the review step, so back from the receipt returns to the card
      // rather than to a confirm button for a purchase that already happened.
      navigate(`/credit/transactions/${response.data.transaction.credit_transaction_id}`, {
        replace: true,
        state: { fresh: true },
      });
    } catch (err) {
      const declined = err?.details?.transaction;

      if (declined) {
        // A decline is a definite answer, with a transaction to show for it.
        attemptKey.current = null;
        navigate(`/credit/transactions/${declined.credit_transaction_id}`, {
          replace: true,
          state: { fresh: true },
        });
        return;
      }

      // Unknown outcome - keep the key, so "Try again" replays this exact
      // purchase. Anything else was refused outright; a retry is a new attempt.
      if (!outcomeUnknown(err)) attemptKey.current = null;
      setSubmitError(err);
      refetch();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  /* ── States that stop a purchase before it starts ───────────────────── */

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay with card" back="/credit" />
        <Skeleton className="h-52 w-full rounded-3xl" />
        <Skeleton className="mt-4 h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (!account) {
    const noLine = loadError?.code === 'NO_CREDIT_LINE' || loadError?.status === 404;
    return (
      <div className="mx-auto w-full max-w-lg">
        <PageHeader title="Pay with card" back="/credit" />
        {noLine ? (
          <Card className="p-6 text-center">
            <p className="text-base font-semibold text-ink">You do not have a credit card yet</p>
            <p className="mt-1 text-sm text-slate">Apply in a couple of minutes.</p>
            <Button variant="mint" size="lg" full className="mt-5" onClick={() => navigate('/credit/apply')}>
              Apply for a credit card
            </Button>
          </Card>
        ) : (
          <ErrorCard error={loadError} title="We could not load your card" onRetry={refetch} />
        )}
      </div>
    );
  }

  if (!account.can_spend) {
    const next = {
      DECLARE_PURPOSE: { title: 'Choose a purpose first', body: 'Tell us what this credit is for before using the card.', cta: 'Choose a purpose', to: '/credit/purpose' },
      ACTIVATE: { title: 'Activate your card first', body: 'Your card is ready - it just needs switching on.', cta: 'Activate card', to: '/credit/activate' },
      UNBLOCK: { title: 'Your card is frozen', body: 'Unfreeze it from your card screen to make payments again.', cta: 'Go to my card', to: '/credit' },
    }[account.next_step] || { title: 'This card cannot be used right now', body: 'Contact support if you think this is a mistake.', cta: 'Go to my card', to: '/credit' };

    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Pay with card" back="/credit" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">{next.title}</p>
          <p className="mt-1 text-sm text-slate">{next.body}</p>
          <Button variant="mint" size="lg" full className="mt-5" onClick={() => navigate(next.to)}>
            {next.cta}
          </Button>
        </Card>
      </div>
    );
  }

  if (busy) {
    return (
      <ProcessingPanel
        title="Authorising your payment"
        subtitle="Checking your available credit. This takes a moment - please do not close this page."
      />
    );
  }

  /* ── Review ─────────────────────────────────────────────────────────── */
  if (reviewing && draft.merchant && draft.amount) {
    const after = Math.max(0, available - amount);

    return (
      <div className="mx-auto w-full max-w-lg animate-fade-up">
        <PageHeader title="Confirm payment" subtitle="Check the details before you pay." back="/credit/spend" />

        <Card className="mb-4 p-6 text-center">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate">You are paying</p>
          <p className="money mt-1 text-4xl font-bold tracking-tight text-ink">{money(amount)}</p>
          <p className="mt-2 truncate text-sm font-medium text-ink">{draft.merchant.trim()}</p>
          <p className="text-2xs text-slate">{categoryLabel(draft.category)}</p>
        </Card>

        <Card className="mb-4 divide-y divide-line py-1">
          <Row label="Card" value={account.card_number_masked} mono />
          <Row label="Available now" value={money(available)} mono />
          <Row label="Available after (estimate)" value={money(after)} mono />
          {draft.note.trim() && <Row label="Note" value={draft.note.trim()} />}
        </Card>

        {submitError && (
          <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-alert" role="alert">
            <p className="font-medium">{friendlyError(submitError)}</p>
            {submitError.recovery && <p className="mt-1 text-xs">{submitError.recovery}</p>}
            {submitError.code === 'KYC_REQUIRED' && (
              <Button variant="outline" size="sm" className="mt-3" onClick={() => navigate('/kyc')}>
                Complete KYC
              </Button>
            )}
          </div>
        )}

        <Button variant="mint" size="lg" full onClick={pay}>
          {submitError && outcomeUnknown(submitError) ? 'Try again safely' : `Pay ${money(amount)}`}
        </Button>
        <p className="mt-3 text-center text-2xs leading-relaxed text-slate">
          Charged to your CashU credit card. Pay it back by your statement due date.
        </p>
      </div>
    );
  }

  /* ── Details ────────────────────────────────────────────────────────── */
  return (
    <div className="mx-auto w-full max-w-lg animate-fade-up">
      <PageHeader title="Pay with card" subtitle="Pay a merchant with your credit card." back="/credit" />

      <CreditCardFace account={account} className="mb-4" />

      <Card className="space-y-5 p-5 sm:p-6">
        <Input
          label="Paying to"
          placeholder="Merchant or shop name"
          value={draft.merchant}
          maxLength={120}
          autoComplete="off"
          onChange={(event) => edit({ merchant: event.target.value })}
          error={errors.merchant}
        />

        <Input
          label="Amount"
          prefix="₹"
          inputMode="decimal"
          placeholder="0"
          value={draft.amount}
          onChange={(event) => edit({ amount: sanitizeAmount(event.target.value) })}
          error={errors.amount}
          hint={`${money(available)} available to spend.`}
        />

        <fieldset>
          <legend className="mb-2 text-sm font-medium text-ink">Category</legend>
          <div className="flex flex-wrap gap-2">
            {MERCHANT_CATEGORIES.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={draft.category === option.value}
                onClick={() => edit({ category: option.value })}
                className={cx(
                  'rounded-full border px-3 py-1.5 text-xs font-medium transition-all active:scale-95',
                  draft.category === option.value
                    ? 'border-mint bg-mint-50 text-ink ring-2 ring-mint/25'
                    : 'border-line bg-canvas text-slate hover:border-ink/20 hover:text-ink',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <Input
          label="Note (optional)"
          placeholder="What was this for?"
          value={draft.note}
          maxLength={200}
          onChange={(event) => edit({ note: event.target.value })}
        />

        <Button variant="mint" size="lg" full onClick={review}>
          Continue
        </Button>
      </Card>
    </div>
  );
}
