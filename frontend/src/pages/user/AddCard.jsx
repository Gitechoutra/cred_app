import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader, IconLock } from '../../components/layout/AppShell';
import { Button, Input, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { groupCardNumber } from '../../utils/format';

/**
 * Link a credit card (PRD FR-003).
 *
 * Zero raw card storage: the number entered here is used locally to derive the
 * BIN (first six digits, an issuer identifier permitted under PCI DSS) and the
 * last four for display. In a live deployment the full number is handed to the
 * Cashfree tokenisation SDK from this page and never reaches CashU's backend -
 * which is what keeps the platform inside PCI DSS SAQ-A.
 */
export default function AddCard() {
  const navigate = useNavigate();
  const toast = useToast();

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
  const debounce = useRef();

  // Identify the issuer as the user types, so the card takes on its brand
  // colour before they finish - and an unsupported card is caught early.
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
        setIssuerError('We could not identify this card issuer.');
      } finally {
        setLooking(false);
      }
    }, 350);

    return () => clearTimeout(debounce.current);
  }, [digits]);

  const [expMonth, expYear] = expiry.split('/');
  const valid =
    digits.length >= 15 &&
    expMonth?.length === 2 &&
    expYear?.length === 2 &&
    issuer?.is_supported;

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
      });

      toast.success('Card linked successfully.');
      navigate(`/cards/${response.data.card_id}`, { replace: true });
    } catch (err) {
      toast.error(err.message);
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Add a card" back="/cards" />

        <form onSubmit={submit} className="space-y-5 px-4 pt-4">
          {/* Live preview - the card takes the issuer's colour as it is typed. */}
          <div
            className="relative overflow-hidden rounded-2xl p-5 transition-colors duration-500"
            style={{ backgroundColor: issuer?.brand_color || '#0A0F0D', minHeight: 150 }}
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -right-8 -top-12 h-40 w-40 rounded-full bg-white/10 blur-2xl"
            />

            <div className="relative flex h-full flex-col justify-between">
              <div className="flex items-start justify-between">
                <p className="text-sm font-semibold text-white">
                  {looking ? 'Identifying…' : issuer?.issuer_bank || 'Your bank'}
                </p>
                <p className="text-2xs uppercase tracking-wider text-white/60">
                  {issuer?.network || ''}
                </p>
              </div>

              <div>
                <p className="money text-lg tracking-[0.18em] text-white/85">
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

          <Input
            label="Card number"
            inputMode="numeric"
            autoFocus
            autoComplete="cc-number"
            placeholder="4556 1400 0000 4821"
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

          <div className="flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3">
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
