import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { isSimulatedCheckout, openCheckout } from '../../api/cashfree';
import { endpoints } from '../../api/client';
import { BankRow, FeeBreakdown } from '../../components/domain';
import { IconBank, IconChevron, IconLock, IconPlus } from '../../components/layout/AppShell';
import { Button, Card, EmptyState, Sheet, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { money, moneyCompact } from '../../utils/format';

/**
 * Credit facility to bank transfer (PRD FR-006).
 *
 * One screen, not a wizard. The amount, the source card, the destination and
 * the full fee disclosure are all visible at once, so the user authorises with
 * everything in view rather than discovering the fee on a later step.
 *
 * The quote is fetched as the amount changes, debounced - PRD 9.2 requires the
 * disclosure before the 3DS challenge, and showing it live is the honest way to
 * meet that.
 */
export default function Transfer() {
  const navigate = useNavigate();
  const toast = useToast();

  const [amount, setAmount] = useState('');
  const [cardId, setCardId] = useState(null);
  const [bankId, setBankId] = useState(null);
  const [quote, setQuote] = useState(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [picker, setPicker] = useState(null);

  const { data: cardsData, loading: cardsLoading } = useFetch(() => endpoints.cards.list(), []);
  const { data: banksData, loading: banksLoading } = useFetch(() => endpoints.banks.list(), []);
  const { data: limits } = useFetch(() => endpoints.transfers.limits(), []);

  const cards = useMemo(
    () => (cardsData?.cards || []).filter((c) => c.status === 'ACTIVE' && c.is_transfer_eligible),
    [cardsData],
  );
  const banks = useMemo(
    () => (banksData?.accounts || []).filter((a) => a.is_payout_eligible),
    [banksData],
  );

  const card = cards.find((c) => c.card_id === cardId) || cards[0] || null;
  const bank = banks.find((b) => b.bank_account_id === bankId)
    || banks.find((b) => b.is_primary)
    || banks[0]
    || null;

  const cardBalance = card ? (card.available_limit ?? card.card_limit ?? 0) : 0;
  const insufficientBalance = Boolean(card && numeric > 0 && numeric > cardBalance);

  const numeric = Number(amount) || 0;
  const minimum = limits?.limits?.minimum ?? 1000;
  const dailyRemaining = limits?.limits?.daily_remaining;

  const debounce = useRef();

  useEffect(() => {
    clearTimeout(debounce.current);

    if (numeric < minimum) {
      setQuote(null);
      setQuoteError('');
      return undefined;
    }

    setQuoting(true);
    debounce.current = setTimeout(async () => {
      try {
        const response = await endpoints.transfers.quote(numeric);
        setQuote(response.data);
        setQuoteError('');
      } catch (err) {
        setQuote(null);
        setQuoteError(err.message);
      } finally {
        setQuoting(false);
      }
    }, 350);

    return () => clearTimeout(debounce.current);
  }, [numeric, minimum]);

  const ready = Boolean(quote && card && bank && !quoting && numeric >= minimum && !insufficientBalance);

  async function submit() {
    if (!ready || submitting) return;
    if (insufficientBalance) {
      toast.error('Insufficient card balance.');
      return;
    }

    setSubmitting(true);

    try {
      const response = await endpoints.transfers.initiate({
        card_id: card.card_id,
        bank_account_id: bank.bank_account_id,
        amount: numeric,
      });

      const transfer = response.data;

      // Live credentials: hand off to Cashfree's hosted checkout for the 3DS2
      // challenge. Card details go browser -> Cashfree and never touch our
      // backend, which is what keeps CashU inside PCI DSS SAQ-A. This redirects
      // the tab, so nothing below runs on success; the issuer returns the user
      // to /transfer/status/<transfer_id> (backend CASHFREE_RETURN_URL).
      if (!isSimulatedCheckout(transfer) && transfer.payment_session_id) {
        await openCheckout(transfer);
        return;
      }

      // Sandbox adapters: there is no hosted 3DS page, so the status screen
      // drives the confirm step itself.
      navigate(`/transfer/status/${transfer.transfer_id}`, {
        state: { transfer, justInitiated: true },
      });
    } catch (err) {
      toast.error(err.message, {
        action: err.recovery ? { label: 'Fix', onClick: () => navigate('/profile') } : undefined,
      });
      setSubmitting(false);
    }
  }

  if (cardsLoading || banksLoading) return <TransferSkeleton />;

  if (limits && !limits.feature_enabled) {
    return (
      <div className="px-4 pt-16">
        <EmptyState
          icon={<IconLock className="h-6 w-6" />}
          title="Transfers are unavailable"
          description="Card-to-bank transfers are temporarily paused. We will let you know as soon as they are back."
          action={<Button variant="outline" onClick={() => navigate('/home')}>Back to home</Button>}
        />
      </div>
    );
  }

  if (!cards.length) {
    return (
      <div className="px-4 pt-16">
        <EmptyState
          title="Link a credit card first"
          description="You need an active credit card to transfer funds to your bank."
          action={<Button variant="mint" onClick={() => navigate('/cards/add')}>Add a card</Button>}
        />
      </div>
    );
  }

  if (!banks.length) {
    return (
      <div className="px-4 pt-16">
        <EmptyState
          icon={<IconBank className="h-6 w-6" />}
          title="Add a verified bank account"
          description="Money can only be sent to an account we have verified belongs to you."
          action={<Button variant="mint" onClick={() => navigate('/banks/add')}>Add account</Button>}
        />
      </div>
    );
  }

  return (
    <div className="animate-fade-up pb-6">
      <header className="px-4 pt-5 pb-2">
        <h1 className="text-xl font-bold text-ink">Transfer to bank</h1>
        <p className="mt-0.5 text-xs text-slate">
          Move funds from your credit card to your verified account.
        </p>
      </header>

      <div className="space-y-4 px-4">
        {/* ── Amount ──────────────────────────────────────────────────── */}
        <section className="rounded-2xl border border-line bg-canvas p-5">
          <label htmlFor="amount" className="text-2xs font-semibold uppercase tracking-wider text-slate">
            Amount to transfer
          </label>

          <div className="mt-2 flex items-center gap-1.5">
            <span className="text-3xl font-bold text-slate-light">₹</span>
            <input
              id="amount"
              inputMode="decimal"
              autoFocus
              placeholder="0"
              value={amount}
              onChange={(event) => {
                const raw = event.target.value.replace(/[^\d.]/g, '');
                // One decimal point, at most two places - paise beyond that
                // cannot be charged anyway.
                const parts = raw.split('.');
                const clean = parts.length > 2
                  ? `${parts[0]}.${parts.slice(1).join('')}`
                  : raw;
                const [whole, decimals] = clean.split('.');
                setAmount(
                  decimals !== undefined ? `${whole}.${decimals.slice(0, 2)}` : whole,
                );
              }}
              className="money w-full bg-transparent text-3xl font-bold text-ink outline-none placeholder:text-slate-light"
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {[5000, 10000, 25000].map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setAmount(String(preset))}
                className="money rounded-full border border-line px-3 py-1 text-xs font-medium text-slate transition hover:border-ink/20 hover:text-ink"
              >
                {moneyCompact(preset)}
              </button>
            ))}
          </div>

          {numeric > 0 && numeric < minimum && (
            <p className="mt-3 text-xs text-alert">
              Minimum transfer is {money(minimum)}.
            </p>
          )}
          {quoteError && <p className="mt-3 text-xs text-alert">{quoteError}</p>}
          {insufficientBalance && (
            <p className="mt-3 text-xs text-alert">
              Insufficient card balance. Available balance: {money(cardBalance)}.
            </p>
          )}

          {dailyRemaining !== undefined && (
            <p className="mt-3 border-t border-line pt-3 text-2xs text-slate">
              <span className="money font-medium text-ink">{money(dailyRemaining)}</span>{' '}
              remaining of your daily limit
            </p>
          )}
        </section>

        {/* ── Source and destination ──────────────────────────────────── */}
        <section className="overflow-hidden rounded-2xl border border-line bg-canvas">
          <SelectorRow
            label="From"
            title={card ? `${card.issuer_bank} ${card.masked_pan}` : 'Choose a card'}
            subtitle={
              card
                ? `${card.network} · Available ${money(card.available_limit ?? card.card_limit)}`
                : undefined
            }
            swatch={card?.brand_color}
            onClick={() => setPicker('card')}
          />
          <div className="border-t border-line" />
          <SelectorRow
            label="To"
            title={bank ? bank.bank_name : 'Choose an account'}
            subtitle={
              bank
                ? `${bank.masked_account}${bank.balance != null ? ` · Balance ${money(bank.balance)}` : ''}`
                : undefined
            }
            icon={<IconBank className="h-4 w-4" />}
            onClick={() => setPicker('bank')}
          />
        </section>

        {/* ── Fee disclosure (PRD 9.2) ────────────────────────────────── */}
        {quoting && numeric >= minimum && (
          <div className="space-y-2 rounded-2xl border border-line bg-mist/60 p-4">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        )}

        {quote && !quoting && <FeeBreakdown quote={quote} className="animate-fade-up" />}

        {/* ── Authorise ───────────────────────────────────────────────── */}
        <Button
          variant="mint"
          size="lg"
          full
          disabled={!ready}
          loading={submitting}
          onClick={submit}
        >
          {quote
            ? `Transfer ${money(quote.net_payout_amount)}`
            : 'Enter an amount'}
        </Button>

        <p className="flex items-start gap-2 px-1 text-2xs leading-relaxed text-slate">
          <IconLock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          You will complete a secure 3D Secure check with your bank. Your card is
          charged only after that succeeds, and money is sent only to accounts
          verified as yours.
        </p>
      </div>

      {/* ── Pickers ─────────────────────────────────────────────────── */}
      <Sheet open={picker === 'card'} onClose={() => setPicker(null)} title="Choose a card">
        <div className="space-y-2 pb-2">
          {cards.map((option) => (
            <button
              key={option.card_id}
              type="button"
              onClick={() => {
                setCardId(option.card_id);
                setPicker(null);
              }}
              className={cx(
                'flex w-full items-center gap-3 rounded-2xl border p-3.5 text-left transition',
                option.card_id === card?.card_id
                  ? 'border-mint ring-2 ring-mint/25'
                  : 'border-line hover:shadow-card',
              )}
            >
              <span
                className="h-10 w-10 shrink-0 rounded-xl"
                style={{ backgroundColor: option.brand_color || '#0A0F0D' }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-ink">{option.issuer_bank}</p>
                <p className="money truncate text-xs text-slate">{option.masked_pan}</p>
              </div>
              {option.available_limit != null && (
                <span className="money shrink-0 text-xs text-slate">
                  {moneyCompact(option.available_limit)}
                </span>
              )}
            </button>
          ))}
        </div>
      </Sheet>

      <Sheet open={picker === 'bank'} onClose={() => setPicker(null)} title="Choose an account">
        <div className="space-y-2 pb-2">
          {banks.map((option) => (
            <BankRow
              key={option.bank_account_id}
              account={option}
              selected={option.bank_account_id === bank?.bank_account_id}
              onClick={() => {
                setBankId(option.bank_account_id);
                setPicker(null);
              }}
            />
          ))}

          <button
            type="button"
            onClick={() => navigate('/banks/add')}
            className="flex w-full items-center gap-3 rounded-2xl border-2 border-dashed border-line p-3.5 text-slate transition hover:border-ink/20 hover:text-ink"
          >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mist">
              <IconPlus className="h-5 w-5" />
            </span>
            <span className="text-sm font-medium">Add another account</span>
          </button>
        </div>
      </Sheet>
    </div>
  );
}

function SelectorRow({ label, title, subtitle, swatch, icon, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 p-3.5 text-left transition active:bg-mist"
    >
      <span className="w-9 shrink-0 text-2xs font-semibold uppercase tracking-wider text-slate">
        {label}
      </span>

      {swatch ? (
        <span className="h-8 w-8 shrink-0 rounded-lg" style={{ backgroundColor: swatch }} />
      ) : (
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-mist text-slate">
          {icon}
        </span>
      )}

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{title}</p>
        {subtitle && <p className="money truncate text-xs text-slate">{subtitle}</p>}
      </div>

      <IconChevron className="h-4 w-4 shrink-0 text-slate-light" />
    </button>
  );
}

function TransferSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-5">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-[148px] w-full rounded-2xl" />
      <Skeleton className="h-[132px] w-full rounded-2xl" />
      <Skeleton className="h-[180px] w-full rounded-2xl" />
    </div>
  );
}
