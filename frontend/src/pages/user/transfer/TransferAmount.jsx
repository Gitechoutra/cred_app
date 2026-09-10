import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { isSimulatedCheckout, openCheckout } from '../../../api/cashfree';
import { newIdempotencyKey } from '../../../api/client';
import {
  getTransferLimits,
  initiateTransfer,
  listBankAccounts,
  listCards,
  payoutEligible,
  quoteTransfer,
} from '../../../api/transfers';
import Button from '../../../components/Button';
import ErrorNotice from '../../../components/ErrorNotice';
import FeeBreakdown from '../../../components/FeeBreakdown';
import Panel from '../../../components/Panel';
import { money, moneyShort } from '../../../utils/money';

/**
 * The amount screen (PRD FR-006 steps 1-5).
 *
 * The whole point of this screen is that nothing is a surprise. The fee, the
 * GST, the exact figure that will hit the card and the exact figure that will
 * reach the bank are all on screen *before* the user is handed to the 3DS
 * challenge - that disclosure is a regulatory requirement, not a nicety.
 *
 * Pressing Continue does not charge anything. It opens a Cashfree order and
 * redirects to their hosted checkout; the card is only debited once Cashfree
 * confirms an authenticated payment, and CashU learns about it by webhook.
 */

const QUOTE_DEBOUNCE_MS = 400;

export default function TransferAmount() {
  const navigate = useNavigate();

  const [cards, setCards] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [limits, setLimits] = useState(null);

  const [cardId, setCardId] = useState('');
  const [bankAccountId, setBankAccountId] = useState('');
  const [amount, setAmount] = useState('');

  const [quote, setQuote] = useState(null);
  const [quoting, setQuoting] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Generated once per intent, not per attempt: if the network drops and the
  // user presses Continue again, replaying the same key returns the original
  // transfer instead of opening a second one against the same card.
  const idempotencyKeyRef = useRef(newIdempotencyKey());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [cardsResponse, accountsResponse, limitsResponse] = await Promise.all([
          listCards(),
          listBankAccounts(),
          getTransferLimits(),
        ]);

        if (cancelled) return;

        const usableCards = (cardsResponse?.cards || []).filter(
          (card) => card.status === 'ACTIVE' && card.is_transfer_eligible,
        );
        const usableAccounts = payoutEligible(accountsResponse?.accounts || []);

        setCards(usableCards);
        setAccounts(usableAccounts);
        setLimits(limitsResponse?.limits || null);

        if (usableCards.length) setCardId(usableCards[0].card_id);
        const primary = usableAccounts.find((a) => a.is_primary) || usableAccounts[0];
        if (primary) setBankAccountId(primary.bank_account_id);
      } catch (cause) {
        if (!cancelled) setLoadError(cause);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const numericAmount = Number(amount);
  const minimum = limits?.minimum ?? 0;

  const amountIsQuotable =
    Number.isFinite(numericAmount) && numericAmount >= minimum && minimum > 0;

  // Re-quote as the user types. The backend owns every figure - recomputing the
  // fee here risks disclosing one number and charging another.
  useEffect(() => {
    if (!amountIsQuotable) {
      setQuote(null);
      return undefined;
    }

    setQuoting(true);
    const timer = setTimeout(async () => {
      try {
        const next = await quoteTransfer(numericAmount);
        setQuote(next);
        setError(null);
      } catch (cause) {
        setQuote(null);
        setError(cause);
      } finally {
        setQuoting(false);
      }
    }, QUOTE_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [numericAmount, amountIsQuotable]);

  const validationMessage = useMemo(() => {
    if (!amount) return null;
    if (!Number.isFinite(numericAmount) || numericAmount <= 0) {
      return 'Enter a valid amount.';
    }
    if (minimum && numericAmount < minimum) {
      return `The minimum transfer is ${money(minimum)}.`;
    }
    if (limits?.single_maximum && numericAmount > limits.single_maximum) {
      return `The most you can send in one transfer is ${money(limits.single_maximum)}.`;
    }
    if (limits?.daily_remaining !== undefined && numericAmount > limits.daily_remaining) {
      return `This exceeds today's remaining limit of ${money(limits.daily_remaining)}.`;
    }
    return null;
  }, [amount, numericAmount, minimum, limits]);

  const canSubmit =
    Boolean(cardId) &&
    Boolean(bankAccountId) &&
    amountIsQuotable &&
    !validationMessage &&
    Boolean(quote) &&
    !quoting &&
    !submitting;

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      if (!canSubmit) return;

      setSubmitting(true);
      setError(null);

      try {
        const transfer = await initiateTransfer({
          cardId,
          bankAccountId,
          amount: numericAmount,
          idempotencyKey: idempotencyKeyRef.current,
        });

        // Sandbox adapters hand back a local stand-in instead of a real
        // Cashfree session, so the flow stays walkable without vendor keys.
        if (isSimulatedCheckout(transfer)) {
          navigate(`/transfer/sandbox/${transfer.transfer_id}`);
          return;
        }

        // Redirects the tab. Nothing below this line runs on success.
        await openCheckout(transfer);
      } catch (cause) {
        setError(
          cause.name === 'ApiError'
            ? cause
            : { message: cause.message, code: 'CHECKOUT_ERROR' },
        );
        setSubmitting(false);
      }
    },
    [canSubmit, cardId, bankAccountId, numericAmount, navigate],
  );

  if (loading) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <div className="h-64 animate-pulse rounded-2xl bg-mist" aria-busy="true" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorNotice error={loadError} />
      </div>
    );
  }

  const blocked = !cards.length || !accounts.length;

  return (
    <div className="mx-auto max-w-lg p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-ink">Transfer to bank</h1>
        <p className="mt-1 text-sm text-slate">
          Move funds from your credit card limit to a verified bank account.
        </p>
      </header>

      {blocked ? (
        <Panel>
          <p className="text-sm text-ink">
            {!cards.length
              ? 'Link a credit card before making a transfer.'
              : 'Add and verify a bank account before making a transfer.'}
          </p>
          <p className="mt-1 text-sm text-slate">
            {!cards.length
              ? 'Your card is tokenised — CashU never stores the number.'
              : 'We send ₹1 to confirm the account belongs to you.'}
          </p>
        </Panel>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <Panel title="From">
            <select
              value={cardId}
              onChange={(event) => setCardId(event.target.value)}
              className="w-full rounded-xl border border-line bg-mist px-4 py-3 text-sm"
            >
              {cards.map((card) => (
                <option key={card.card_id} value={card.card_id}>
                  {card.card_issuer_bank} {card.masked_pan}
                </option>
              ))}
            </select>
          </Panel>

          <Panel title="To">
            <select
              value={bankAccountId}
              onChange={(event) => setBankAccountId(event.target.value)}
              className="w-full rounded-xl border border-line bg-mist px-4 py-3 text-sm"
            >
              {accounts.map((account) => (
                <option key={account.bank_account_id} value={account.bank_account_id}>
                  {account.bank_name} {account.masked_account}
                  {account.is_primary ? ' · Primary' : ''}
                </option>
              ))}
            </select>
          </Panel>

          <Panel title="Amount">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-semibold text-slate">₹</span>
              <input
                type="number"
                inputMode="decimal"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0"
                min={minimum || undefined}
                step="1"
                autoFocus
                className="tabular w-full border-none bg-transparent p-0 text-3xl font-semibold text-ink placeholder:text-line focus:ring-0"
              />
            </div>

            {limits && (
              <p className="mt-2 text-xs text-slate tabular">
                {moneyShort(limits.minimum)} – {moneyShort(limits.single_maximum)} per
                transfer · {moneyShort(limits.daily_remaining)} left today
              </p>
            )}

            {validationMessage && (
              <p className="mt-2 text-sm text-alert">{validationMessage}</p>
            )}
          </Panel>

          {(quote || quoting) && !validationMessage && (
            <Panel title="Before you continue">
              <FeeBreakdown quote={quote} loading={quoting && !quote} />
            </Panel>
          )}

          <ErrorNotice error={error} />

          <Button
            type="submit"
            variant="primary"
            loading={submitting}
            disabled={!canSubmit}
            className="w-full"
          >
            {submitting
              ? 'Opening secure checkout…'
              : quote
                ? `Continue · ${money(quote.total_charged_to_card ?? quote.breakdown?.total_charged_to_card)}`
                : 'Continue'}
          </Button>

          <p className="text-center text-xs text-slate">
            You will authenticate with your bank. Your card is charged only after
            that succeeds.
          </p>
        </form>
      )}
    </div>
  );
}
