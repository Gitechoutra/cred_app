import { IconShield } from '../../../components/layout/AppShell';
import { CreditCard } from '../../../components/marketing/Showcase';
import { CheckMark, Container, Eyebrow, FadeIn } from './shared';

const GUARANTEES = [
  {
    title: 'Your card number never reaches us',
    body: 'Card details go from your browser straight to a licensed tokenisation partner. CashU keeps a network token and the last four digits, never the full number, the CVV or the PIN.',
  },
  {
    title: 'Money only moves to your own account',
    body: 'Every bank account you add is verified by depositing ₹1 and matching the name your bank holds against your KYC record. Third-party accounts are refused outright.',
  },
  {
    title: 'Nothing is debited without warning',
    body: 'Auto-pay sends notice 48 hours before every debit, double the 24 hours RBI requires, and you can pause or cancel any mandate up to a day beforehand.',
  },
  {
    title: 'Every rupee is auditable',
    body: 'Each movement is a double-entry journal that is never edited or deleted. Corrections are posted as new entries, and the ledger is re-verified nightly.',
  },
];

/**
 * The one dark band in the middle of the page. Security is the section people
 * read slowest, and the change of ground tells them this part is different.
 */
export function Security() {
  return (
    <section id="security" className="relative isolate overflow-hidden bg-ink py-16 lg:py-24">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <span className="orb animate-drift -left-24 top-10 h-80 w-80 bg-mint/20" />
        <span className="orb animate-drift-slow -bottom-24 right-0 h-72 w-72 bg-mint/10" />
      </div>

      <Container className="grid gap-12 lg:grid-cols-2 lg:items-center">
        <FadeIn>
          <Eyebrow icon={IconShield} tone="dark">Security</Eyebrow>
          <h2 className="mt-5 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Four promises the product is built around
          </h2>
          <p className="mt-4 text-base leading-relaxed text-white/60">
            These are not policies written after the fact. Each one is enforced
            in the code. A credit card cannot pay a loan EMI because that option
            does not exist in the system, not because a check happens to catch it.
          </p>

          <div className="mt-10 hidden lg:block">
            <CreditCard
              label="HDFC Regalia"
              network="visa"
              last4="4821"
              sheen
              gradient="linear-gradient(135deg,#141A18 0%,#1F2725 45%,#00614B 100%)"
              className="animate-float"
            />
          </div>
        </FadeIn>

        <ul className="space-y-4">
          {GUARANTEES.map((item, index) => (
            <FadeIn as="li" key={item.title} delay={index * 70}>
              <div className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04] p-5 transition-all duration-base ease-glide hover:-translate-y-0.5 hover:border-mint/40 hover:bg-white/[0.07]">
                <div className="relative flex items-start gap-3.5">
                  <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-mint text-ink transition-transform duration-base ease-glide group-hover:scale-110">
                    <CheckMark />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold text-white">{item.title}</h3>
                    <p className="mt-1.5 text-xs leading-relaxed text-white/60">{item.body}</p>
                  </div>
                </div>
              </div>
            </FadeIn>
          ))}
        </ul>
      </Container>
    </section>
  );
}
