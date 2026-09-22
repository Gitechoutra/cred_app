import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { BankLogo } from '../../components/domain';
import { PageHeader, IconLock, IconChevron, IconPlus } from '../../components/layout/AppShell';
import { Button, Input, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { SUPPORTED_BANKS, searchBanks } from '../../data/supportedBanks';
import { groupCardNumber } from '../../utils/format';

function IconSearch(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" {...props}>
      <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.75" />
      <path d="M12.5 12.5L16.5 16.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}

function IconClose(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" {...props}>
      <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Add / Link a credit card (PRD FR-003).
 *
 * Updated Flow:
 * 1. Search-First "Select Your Bank" screen:
 *    - Prominent, comfortable 54px search bar.
 *    - Before typing: displays ONLY the Popular Banks suggestion row
 *      (SBI Card, HDFC Bank, ICICI Bank, Axis Bank, Kotak, Union Bank) + Add Bank.
 *    - When typing: dynamically reveals matching banks with official logos.
 *    - Empty state: clean "No banks found" with an "Add Bank" option.
 * 2. Card Details form:
 *    - Live preview displaying the authentic official bank logo, bank name,
 *      and issuer brand colour.
 *    - Allows switching bank via "Change bank" without losing input.
 */
export default function AddCard() {
  const navigate = useNavigate();
  const toast = useToast();

  // Step state: 'bank' | 'details'
  const [step, setStep] = useState('bank');
  const [selectedBank, setSelectedBank] = useState(null);

  // Search & custom bank state
  const [searchQuery, setSearchQuery] = useState('');
  const [isAddingCustomBank, setIsAddingCustomBank] = useState(false);
  const [customBankInput, setCustomBankInput] = useState('');

  // Card form state
  const [number, setNumber] = useState('');
  const [expiry, setExpiry] = useState('');
  const [name, setName] = useState('');
  const [limit, setLimit] = useState('');
  const [dueDay, setDueDay] = useState('');
  const [issuer, setIssuer] = useState(null);
  const [issuerError, setIssuerError] = useState('');
  const [loading, setLoading] = useState(false);
  const [looking, setLooking] = useState(false);

  const digits = number.replace(/\D/g, '');

  // Absent in production - the endpoint 404s, so the picker simply never
  // renders and nothing else on this screen changes.
  const [testCards, setTestCards] = useState(null);

  useEffect(() => {
    let cancelled = false;
    endpoints.cards
      .testCards()
      .then((response) => !cancelled && setTestCards(response.data))
      .catch(() => {
        /* Test mode is off. Not an error worth showing anyone. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Fill the form from a catalogue card, so nobody retypes sixteen digits. */
  function useTestCard(card) {
    setNumber(card.formatted);
    setExpiry(`${card.expiry_month}/${String(card.expiry_year).slice(-2)}`);
    setName(card.cardholder_name);
    setLimit(String(card.card_limit));
    setSelectedBank({
      name: card.issuer_bank,
      brandColor: card.brand_color,
      sampleBin: card.bin,
    });
  }
  const debounce = useRef();

  // Filter banks based on search input (returns empty array if no query)
  const isSearching = Boolean(searchQuery.trim());
  const matchingBanks = useMemo(() => searchBanks(searchQuery), [searchQuery]);

  // Popular banks row (SBI Card, HDFC Bank, ICICI Bank, Axis Bank, Kotak, Union Bank)
  const popularBanks = useMemo(
    () => SUPPORTED_BANKS.filter((b) => b.popular),
    [],
  );

  function handleSelectBank(bank) {
    setSelectedBank(bank);
    setStep('details');
  }

  function handleCustomBankSubmit(e) {
    e?.preventDefault();
    const trimmed = (customBankInput || searchQuery).trim();
    if (!trimmed) return;

    const customBank = {
      id: `custom-${Date.now()}`,
      name: trimmed,
      shortName: trimmed,
      brandColor: '#0A0F0D',
      networks: ['Credit Card'],
      isCustom: true,
    };
    setSelectedBank(customBank);
    setIsAddingCustomBank(false);
    setCustomBankInput('');
    setStep('details');
  }

  // Identify issuer via BIN lookup when user enters card digits
  useEffect(() => {
    clearTimeout(debounce.current);
    setIssuerError('');

    if (digits.length < 6) {
      setIssuer(null);
      return undefined;
    }

    setLooking(true);
    debounce.current = setTimeout(async () => {
      try {
        const response = await endpoints.cards.lookupBin(digits.slice(0, 6));
        setIssuer(response.data);
        if (!response.data.is_supported) {
          setIssuerError('Only credit cards are supported.');
        }
      } catch {
        setIssuer(null);
        if (!selectedBank) {
          setIssuerError('We could not identify this card issuer.');
        }
      } finally {
        setLooking(false);
      }
    }, 350);

    return () => clearTimeout(debounce.current);
  }, [digits, selectedBank]);

  const [expMonth, expYear] = expiry.split('/');

  const isCardSupported = issuer ? issuer.is_supported : Boolean(selectedBank);
  const valid =
    digits.length >= 15 &&
    expMonth?.length === 2 &&
    expYear?.length === 2 &&
    isCardSupported &&
    !issuerError;

  function onExpiryChange(value) {
    const raw = value.replace(/\D/g, '').slice(0, 4);
    setExpiry(raw.length > 2 ? `${raw.slice(0, 2)}/${raw.slice(2)}` : raw);
  }

  async function submit(event) {
    event.preventDefault();
    if (!valid || loading) return;

    setLoading(true);

    try {
      const response = await endpoints.cards.link({
        bin: digits.slice(0, 6),
        last4: digits.slice(-4),
        expiry_month: expMonth,
        expiry_year: `20${expYear}`,
        cardholder_name: name.trim() || undefined,
        card_limit: limit ? Number(limit) : undefined,
        due_day: dueDay ? Number(dueDay) : undefined,
        issuer_bank: issuer?.issuer_bank || selectedBank?.name || undefined,
        brand_color: issuer?.brand_color || selectedBank?.brandColor || undefined,
      });

      toast.success('Card linked successfully.');
      navigate(`/cards/${response.data.card_id}`, { replace: true });
    } catch (err) {
      toast.error(err.message);
      setLoading(false);
    }
  }

  const activeBrandColor = issuer?.brand_color || selectedBank?.brandColor || '#0A0F0D';
  const activeBankName = looking
    ? 'Identifying…'
    : issuer?.issuer_bank || selectedBank?.name || 'Your bank';
  const activeNetwork =
    issuer?.network || selectedBank?.networks?.[0] || 'CREDIT';

  /* ─────────────────────────────────────────────────────────────────────────────
     STEP 1: SELECT YOUR BANK (SEARCH-FIRST)
     ───────────────────────────────────────────────────────────────────────────── */
  if (step === 'bank') {
    return (
      <div>
        <div className="mx-auto w-full max-w-2xl">
          <PageHeader
            title="Select your bank"
            subtitle="Choose the bank that issued your credit card"
            back="/cards"
          />

          <div className="space-y-6 px-4 pt-1">
            {/* Search Input: Increased height (54px / h-[54px]), prominent & readable */}
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-4 sm:left-5 flex items-center text-slate">
                <IconSearch className="h-5 w-5" />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search bank"
                autoFocus
                className={cx(
                  'h-[54px] w-full rounded-2xl border border-line bg-canvas pl-12 sm:pl-14 pr-12 text-base text-ink font-medium outline-none transition',
                  'placeholder:text-slate-light placeholder:font-normal focus:border-ink/40',
                )}
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  aria-label="Clear search"
                  className="absolute inset-y-0 right-0 flex items-center pr-4 text-slate hover:text-ink transition"
                >
                  <IconClose className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* BEFORE TYPING: DO NOT show full list. Show ONLY the Popular Banks row + Add Bank */}
            {!isSearching ? (
              <div className="space-y-5">
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-2xs font-bold uppercase tracking-wider text-slate">
                      Popular banks
                    </p>
                  </div>

                  {/* Suggestion list of 6 popular banks: SBI Card, HDFC Bank, ICICI Bank, Axis Bank, Kotak, Union Bank */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {popularBanks.map((bank) => (
                      <button
                        key={bank.id}
                        type="button"
                        onClick={() => handleSelectBank(bank)}
                        className={cx(
                          'group flex flex-col items-center justify-center gap-2 rounded-2xl border border-line bg-canvas p-3.5 sm:p-4 text-center transition-all duration-200',
                          'hover:border-mint hover:shadow-card hover:-translate-y-0.5 active:scale-[0.98]',
                        )}
                      >
                        <BankLogo bankId={bank.id} bankName={bank.name} variant="popular" />
                        <span className="text-xs font-semibold text-ink group-hover:text-ink">
                          {bank.shortName}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Add Bank option directly below popular banks */}
                {!isAddingCustomBank ? (
                  <button
                    type="button"
                    onClick={() => setIsAddingCustomBank(true)}
                    className={cx(
                      'flex w-full items-center gap-3.5 rounded-2xl border border-dashed border-line bg-canvas/80 p-4 text-left transition',
                      'hover:border-ink hover:bg-mist/50 active:scale-[0.99]',
                    )}
                  >
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mist text-ink">
                      <IconPlus className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-ink">Don't see your bank?</p>
                      <p className="text-2xs text-slate">Add an unlisted bank to continue</p>
                    </div>
                    <span className="text-xs font-semibold text-mint-700">Add bank</span>
                  </button>
                ) : (
                  /* Inline Add Bank Form */
                  <div className="rounded-2xl border-2 border-mint/40 bg-mint-50/50 p-4.5 transition animate-in fade-in">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-bold text-ink">Add unlisted bank</h3>
                        <p className="text-2xs text-slate mt-0.5">
                          Enter the name of your bank to proceed with card linking
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setIsAddingCustomBank(false)}
                        className="rounded-lg p-1 text-slate hover:text-ink"
                      >
                        <IconClose className="h-4 w-4" />
                      </button>
                    </div>

                    <form onSubmit={handleCustomBankSubmit} className="mt-3 flex gap-2">
                      <input
                        type="text"
                        value={customBankInput}
                        onChange={(e) => setCustomBankInput(e.target.value)}
                        placeholder="e.g. DBS Bank India, HSBC"
                        autoFocus
                        className="h-11 flex-1 rounded-xl border border-line bg-canvas px-3.5 text-sm text-ink outline-none focus:border-ink/40"
                      />
                      <Button
                        type="submit"
                        variant="primary"
                        size="md"
                        disabled={!customBankInput.trim()}
                      >
                        Continue
                      </Button>
                    </form>
                  </div>
                )}
              </div>
            ) : (
              /* WHEN USER STARTS TYPING: DYNAMICALLY REVEAL MATCHING BANKS ONLY */
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-2xs font-bold uppercase tracking-wider text-slate">
                    Matching banks ({matchingBanks.length})
                  </p>
                </div>

                {matchingBanks.length > 0 ? (
                  <div className="space-y-2">
                    {matchingBanks.map((bank) => (
                      <button
                        key={bank.id}
                        type="button"
                        onClick={() => handleSelectBank(bank)}
                        className={cx(
                          'group flex w-full items-center gap-3.5 rounded-2xl border border-line bg-canvas p-3.5 text-left transition',
                          'hover:border-mint hover:shadow-card hover:bg-mist/30 active:scale-[0.99]',
                        )}
                      >
                        <BankLogo bankId={bank.id} bankName={bank.name} size="md" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-ink group-hover:text-ink">
                            {bank.name}
                          </p>
                          <p className="mt-0.5 truncate text-2xs text-slate">
                            {bank.networks.join(' · ')}
                          </p>
                        </div>
                        <IconChevron className="h-4 w-4 shrink-0 text-slate-light group-hover:text-ink transition-colors" />
                      </button>
                    ))}

                    {/* Also allow adding as custom if unlisted */}
                    <button
                      type="button"
                      onClick={() => {
                        handleSelectBank({
                          id: `custom-${Date.now()}`,
                          name: searchQuery.trim(),
                          shortName: searchQuery.trim(),
                          brandColor: '#0A0F0D',
                          networks: ['Credit Card'],
                          isCustom: true,
                        });
                      }}
                      className={cx(
                        'flex w-full items-center gap-3.5 rounded-2xl border border-dashed border-line bg-canvas/60 p-3.5 text-left transition',
                        'hover:border-ink hover:bg-mist/40 active:scale-[0.99]',
                      )}
                    >
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mist text-ink">
                        <IconPlus className="h-5 w-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-ink">
                          Add &ldquo;{searchQuery.trim()}&rdquo; as bank
                        </p>
                        <p className="text-2xs text-slate">Link card with this bank name</p>
                      </div>
                      <IconChevron className="h-4 w-4 shrink-0 text-slate-light" />
                    </button>
                  </div>
                ) : (
                  /* Clean "No banks found" state with "Add Bank" option */
                  <div className="rounded-2xl border border-line bg-canvas p-8 text-center animate-in fade-in">
                    <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-mist text-slate">
                      <IconSearch className="h-6 w-6" />
                    </div>
                    <h3 className="text-base font-semibold text-ink">No banks found</h3>
                    <p className="mt-1 text-xs text-slate max-w-sm mx-auto">
                      We couldn't find a bank matching &ldquo;{searchQuery}&rdquo;. You can add your bank to proceed.
                    </p>
                    <div className="mt-5 flex justify-center">
                      <Button
                        variant="mint"
                        size="md"
                        onClick={() => {
                          handleSelectBank({
                            id: `custom-${Date.now()}`,
                            name: searchQuery.trim(),
                            shortName: searchQuery.trim(),
                            brandColor: '#0A0F0D',
                            networks: ['Credit Card'],
                            isCustom: true,
                          });
                        }}
                      >
                        Add &ldquo;{searchQuery.trim()}&rdquo; as Bank
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  /* ─────────────────────────────────────────────────────────────────────────────
     STEP 2: CARD DETAILS (WITH SELECTED BANK EMBEDDED)
     ───────────────────────────────────────────────────────────────────────────── */
  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Add a card"
          subtitle={selectedBank?.name ? `Card issued by ${selectedBank.name}` : undefined}
          back={() => setStep('bank')}
        />

        <form onSubmit={submit} className="space-y-5 px-4 pt-1">
          {/* Selected bank pill with Change bank action */}
          {selectedBank && (
            <div className="flex items-center justify-between rounded-xl bg-mist px-3.5 py-2.5 border border-line">
              <div className="flex items-center gap-2.5 min-w-0">
                <BankLogo
                  bankId={selectedBank.id}
                  bankName={selectedBank.name}
                  size="xs"
                />
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-ink">
                    {selectedBank.name}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setStep('bank')}
                className="shrink-0 text-xs font-semibold text-mint-700 hover:text-mint-800 hover:underline transition"
              >
                Change bank
              </button>
            </div>
          )}

          {/* Live card preview with official bank logo and bank brand colour */}
          <div
            className="relative overflow-hidden rounded-2xl p-5 transition-colors duration-500 shadow-card"
            style={{ backgroundColor: activeBrandColor, minHeight: 160 }}
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -right-8 -top-12 h-40 w-40 rounded-full bg-white/10 blur-2xl"
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/20"
            />

            <div className="relative flex h-full flex-col justify-between">
              {/* Header: Official bank logo + Bank name + Network */}
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <BankLogo
                    bankId={selectedBank?.id}
                    bankName={activeBankName}
                    variant="preview"
                  />
                  <p className="truncate text-sm font-semibold text-white">
                    {activeBankName}
                  </p>
                </div>
                <p className="text-2xs uppercase tracking-wider text-white/75 font-medium">
                  {activeNetwork}
                </p>
              </div>

              {/* Card number digits */}
              <div className="mt-5">
                <p className="money text-lg tracking-[0.18em] text-white/90">
                  {groupCardNumber(digits) || '•••• •••• •••• ••••'}
                </p>
                <div className="mt-3 flex items-end justify-between">
                  <p className="truncate text-2xs uppercase tracking-wide text-white/60">
                    {name || 'CARDHOLDER NAME'}
                  </p>
                  <p className="money text-2xs text-white/60">{expiry || 'MM/YY'}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Test mode. Rendered only when the server says so, and stated
              plainly rather than tucked away - somebody looking at this screen
              should never be unsure whether a real card is about to be
              charged. */}
          {testCards?.cards?.length > 0 && (
            <div className="mb-5 overflow-hidden rounded-2xl border border-amber-300 bg-amber-50">
              <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-100/70 px-4 py-2.5">
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-amber-500 text-white">
                  <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
                    <path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" strokeLinejoin="round" />
                  </svg>
                </span>
                <p className="text-2xs font-bold uppercase tracking-[0.14em] text-amber-900">
                  Test mode — simulated cards
                </p>
              </div>

              <div className="px-4 py-3.5">
                <p className="text-xs leading-relaxed text-amber-900/80">
                  {testCards.notice}
                </p>

                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {testCards.cards.map((card) => (
                    <button
                      key={card.number}
                      type="button"
                      onClick={() => useTestCard(card)}
                      className={cx(
                        'group rounded-xl border border-amber-200 bg-canvas p-3 text-left',
                        'transition-all duration-base ease-glide',
                        'hover:-translate-y-0.5 hover:border-amber-400 hover:shadow-card',
                        'active:translate-y-0 active:scale-[0.98]',
                      )}
                    >
                      <p className="text-xs font-bold text-ink">{card.label}</p>
                      <p className="money mt-1 text-2xs tracking-wider text-slate">
                        {card.formatted}
                      </p>
                      <p className="mt-1.5 text-2xs leading-relaxed text-slate">
                        {card.description}
                      </p>
                    </button>
                  ))}
                </div>

                <p className="mt-3 text-2xs text-amber-900/70">
                  CVV {testCards.cards[0]?.cvv} for every card. Pick one to fill
                  the form.
                </p>
              </div>
            </div>
          )}

          <Input
            label="Card number"
            inputMode="numeric"
            autoFocus
            autoComplete="cc-number"
            placeholder={
              selectedBank?.sampleBin
                ? `${selectedBank.sampleBin.slice(0, 4)} ${selectedBank.sampleBin.slice(4)}00 0000 0000`
                : '4556 1400 0000 4821'
            }
            value={groupCardNumber(digits)}
            error={issuerError}
            onChange={(event) => setNumber(event.target.value)}
          />

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Expiry"
              inputMode="numeric"
              autoComplete="cc-exp"
              placeholder="MM/YY"
              value={expiry}
              maxLength={5}
              onChange={(event) => onExpiryChange(event.target.value)}
            />
            <Input
              label="Due day"
              hint="Day of month"
              inputMode="numeric"
              placeholder="10"
              value={dueDay}
              maxLength={2}
              onChange={(event) => setDueDay(event.target.value.replace(/\D/g, ''))}
            />
          </div>

          <Input
            label="Name on card"
            hint="Optional"
            autoComplete="cc-name"
            placeholder="VIKRAM SHARMA"
            value={name}
            onChange={(event) => setName(event.target.value.toUpperCase())}
          />

          <Input
            label="Credit limit"
            hint="Helps us show your utilisation. You can add it later."
            inputMode="numeric"
            prefix="₹"
            placeholder="300000"
            value={limit}
            onChange={(event) => setLimit(event.target.value.replace(/\D/g, ''))}
          />

          <div className="flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3 border border-line/60">
            <IconLock className="mt-0.5 h-4 w-4 shrink-0 text-slate" />
            <p className="text-xs leading-relaxed text-slate">
              CashU never stores your full card number, CVV or PIN. Your card is
              tokenised with your bank under RBI Card-on-File rules — we keep only
              the token and the last four digits.
            </p>
          </div>

          <Button type="submit" variant="mint" size="lg" full disabled={!valid} loading={loading}>
            Link card
          </Button>
        </form>
      </div>
    </div>
  );
}
