import { BankLogo, resolveBankId } from '../../../components/domain/BankLogo';
import { SUPPORTED_BANKS } from '../../../data/supportedBanks';
import { FadeIn } from './shared';

// Only issuers we hold a real logo for: a monogram tile in a logo wall reads
// as a gap, not as a bank.
const ISSUERS = SUPPORTED_BANKS.filter((bank) => resolveBankId(bank.id));

/**
 * The issuers CashU can link, scrolling past. Two copies of the row make the
 * loop seamless; the second is hidden from assistive tech so a screen reader
 * hears each bank once. Under reduced motion it becomes a static wrapped row
 * (landing.css).
 */
export function BankMarquee() {
  return (
    <section aria-labelledby="lp-issuers" className="mt-10 border-y border-line bg-mist/50 py-9">
      <FadeIn>
        <p id="lp-issuers" className="px-4 text-center text-2xs font-semibold uppercase tracking-[0.18em] text-slate">
          Works with the cards you already carry
        </p>
      </FadeIn>

      <div className="lp-marquee relative mt-6 overflow-hidden">
        <div className="lp-marquee-track flex w-max items-center">
          <LogoRow />
          <LogoRow duplicate />
        </div>
      </div>
    </section>
  );
}

function LogoRow({ duplicate = false }) {
  return (
    <ul
      className={duplicate ? 'lp-marquee-dup flex items-center' : 'flex flex-wrap items-center justify-center'}
      aria-hidden={duplicate || undefined}
    >
      {ISSUERS.map((bank) => (
        // Padding, not gap: the gap after the last item has to exist too, or
        // the halves differ in width and the loop jumps.
        <li key={bank.id} className="lp-logo flex w-40 shrink-0 justify-center px-5" title={bank.name}>
          <BankLogo bankId={bank.id} bankName={bank.name} variant="popular" />
        </li>
      ))}
    </ul>
  );
}
