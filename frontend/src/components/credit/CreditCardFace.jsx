import { cx } from '../ui';
import { money } from '../../utils/format';

/**
 * The credit card, as an object.
 *
 * Everything on this face comes from the server, and the number is the masked
 * one - BIN, filler, last four. The digits in between are not stored anywhere in
 * the platform, so this component could not render them if it tried, which is
 * the point: there is no code path from a card face to a full PAN.
 *
 * No CVV appears here or anywhere else. A real issuer prints one; this platform
 * never generates or holds one, so showing a placeholder would imply a
 * capability that does not exist.
 *
 * The dimming for a non-active card is deliberate rather than decorative: a
 * frozen or unactivated card that looks identical to a live one is how somebody
 * ends up at a till wondering why it declined.
 */

const NETWORK_LABEL = {
  RUPAY: 'RuPay',
  VISA: 'VISA',
  MASTERCARD: 'Mastercard',
};

export function CreditCardFace({ account, className, showBalance = true }) {
  if (!account) return null;

  const live = account.status === 'ACTIVE';
  const frozen = account.status === 'BLOCKED';

  return (
    <div
      className={cx(
        // A minimum height rather than an aspect ratio: with overflow hidden,
        // an aspect ratio clips the contents on a narrow phone instead of
        // growing to fit them.
        'relative w-full min-h-[13.5rem] overflow-hidden rounded-3xl p-5 text-white sm:min-h-[15rem] sm:p-6',
        'bg-gradient-to-br from-ink via-[#101a24] to-[#04121b]',
        'shadow-[0_24px_48px_-20px_rgba(10,15,13,0.55)] ring-1 ring-white/10',
        'transition-all duration-slow ease-glide',
        !live && 'opacity-70 saturate-[0.4]',
        className,
      )}
    >
      {/* Mint bloom, bottom right. Purely decorative, so it is hidden from
          assistive tech rather than described. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-16 -right-12 h-48 w-48 rounded-full bg-mint/20 blur-3xl"
      />
      {/* A single soft highlight across the top, the way light sits on a
          laminated card. Subtle on purpose - this is a card, not a poster. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/[0.07] to-transparent"
      />

      <div className="relative flex items-start justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.18em] text-white/50">
            CashU Credit
          </p>
          {showBalance && (
            <p className="money mt-2 text-2xl font-bold tracking-tight">
              {money(account.available_credit)}
            </p>
          )}
          {showBalance && (
            <p className="mt-0.5 text-2xs text-white/50">
              available of {money(account.credit_limit)}
            </p>
          )}
        </div>

        {!live && (
          <span className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-2xs font-semibold uppercase tracking-wider">
            {frozen ? 'Frozen' : 'Not active'}
          </span>
        )}
      </div>

      {/* Chip and contactless mark. Decorative: they say "card" at a glance
          and carry no data. */}
      <div className="relative mt-5 flex items-center gap-3" aria-hidden="true">
        <span className="h-7 w-10 rounded-md bg-gradient-to-br from-[#e9d9a6] via-[#c9b37a] to-[#9c8650] shadow-inner">
          <span className="block h-full w-full rounded-md bg-[linear-gradient(90deg,transparent_45%,rgba(0,0,0,0.18)_46%,rgba(0,0,0,0.18)_54%,transparent_55%),linear-gradient(0deg,transparent_45%,rgba(0,0,0,0.18)_46%,rgba(0,0,0,0.18)_54%,transparent_55%)]" />
        </span>
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-white/60" fill="none">
          <path d="M8 7.5a6.5 6.5 0 010 9M11.5 5a10 10 0 010 14M15 3a13.5 13.5 0 010 18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </div>

      <p className="money relative mt-4 truncate text-base tracking-[0.16em] text-white/90 sm:text-lg sm:tracking-[0.2em]">
        {account.card_number_masked}
      </p>

      <div className="relative mt-5 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-2xs uppercase tracking-wider text-white/40">
            Cardholder
          </p>
          <p className="truncate text-sm font-medium tracking-wide">
            {account.name_on_card}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-2xs uppercase tracking-wider text-white/40">Expires</p>
          <p className="money text-sm font-medium">{account.expiry}</p>
        </div>

        <div className="shrink-0">
          <p className="text-sm font-bold italic tracking-tight">
            {NETWORK_LABEL[account.card_network] || account.card_network}
          </p>
        </div>
      </div>
    </div>
  );
}
