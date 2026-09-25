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
        'relative overflow-hidden rounded-2xl p-5 text-white shadow-lg',
        'bg-gradient-to-br from-ink via-[#101a24] to-[#04121b]',
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

      <p className="money relative mt-7 text-lg tracking-[0.2em] text-white/90">
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
