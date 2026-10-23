import { useNavigate } from 'react-router-dom';

import { Logo } from '../../../components/layout/AppShell';
import { Button, cx } from '../../../components/ui';
import { NAV_LINKS } from './Nav';
import { ArrowRight, Container, FadeIn } from './shared';

export function FinalCta() {
  const navigate = useNavigate();

  return (
    <section className="pb-16 lg:pb-24">
      <Container>
        <FadeIn>
          <div className="mesh relative overflow-hidden rounded-3xl bg-[linear-gradient(120deg,#0A0F0D_0%,#14211D_38%,#00312a_62%,#0A0F0D_100%)] px-6 py-14 text-center sm:px-12 lg:py-20">
            <span aria-hidden="true" className="orb animate-drift -left-20 -top-20 h-64 w-64 bg-mint/30" />
            <span aria-hidden="true" className="orb animate-drift-slow -bottom-24 -right-16 h-64 w-64 bg-mint/25" />

            <div className="relative mx-auto max-w-2xl">
              <h2 className="text-3xl font-bold tracking-tight text-white sm:text-5xl">
                Put every card and EMI in one place
              </h2>
              <p className="mt-4 text-base leading-relaxed text-white/60">
                Takes about a minute. All you need is your mobile number.
              </p>

              <div className="mt-9 flex flex-wrap justify-center gap-3">
                <Button variant="mint" size="lg" className="group" onClick={() => navigate('/signin')}>
                  Create your account
                  <span className="transition-transform duration-base ease-glide group-hover:translate-x-0.5">
                    <ArrowRight />
                  </span>
                </Button>
                <Button
                  variant="ghost"
                  size="lg"
                  className="text-white/70 hover:bg-white/10 hover:text-white"
                  onClick={() => navigate('/admin/login')}
                >
                  Staff? Admin login
                </Button>
              </div>
            </div>
          </div>
        </FadeIn>
      </Container>
    </section>
  );
}

export function Footer() {
  const navigate = useNavigate();

  return (
    <footer className="border-t border-line bg-mist">
      <Container className="py-12">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <Logo className="h-8 w-8" />
              <p className="text-base font-bold tracking-tight text-ink">CashU</p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate">
              Your credit cards and EMIs, under one glass pane.
            </p>
          </div>

          <FooterColumn title="Sign in">
            <FooterAction strong onClick={() => navigate('/signin')}>User login</FooterAction>
            <FooterAction onClick={() => navigate('/signin/mpin')}>Sign in with MPIN</FooterAction>
            <FooterAction onClick={() => navigate('/admin/login')}>Admin login</FooterAction>
          </FooterColumn>

          <FooterColumn title="Product">
            {NAV_LINKS.map((link) => (
              <a key={link.id} href={`#${link.id}`} className={LINK}>{link.label}</a>
            ))}
          </FooterColumn>

          <FooterColumn title="Support">
            {/* Support lives inside the member app, so these route into it
                rather than pointing at pages that do not exist. */}
            <FooterAction onClick={() => navigate('/signin')}>Help &amp; support</FooterAction>
            <FooterAction onClick={() => navigate('/signin')}>Raise a request</FooterAction>
          </FooterColumn>
        </div>

        <div className="mt-10 flex flex-col gap-3 border-t border-line pt-6 sm:flex-row sm:items-start sm:justify-between">
          <p className="max-w-3xl text-2xs leading-relaxed text-slate">
            CashU is a technology platform operating with licensed payment
            partners. It is not a bank, does not issue credit and does not hold
            customer funds. Card tokenisation follows RBI
            Card-on-File rules; personal data is handled under the DPDPA 2023. By
            continuing you agree to our Terms of Service and Privacy Policy.
          </p>
          <p className="shrink-0 text-2xs text-slate">© {new Date().getFullYear()} CashU</p>
        </div>
      </Container>
    </footer>
  );
}

const LINK_BASE = 'block text-sm transition-colors duration-base hover:text-ink hover:underline';
const LINK = `${LINK_BASE} font-medium text-slate`;

function FooterColumn({ title, children }) {
  return (
    <div>
      <p className="text-2xs font-bold uppercase tracking-[0.14em] text-slate">{title}</p>
      <div className="mt-3 space-y-2">{children}</div>
    </div>
  );
}

function FooterAction({ onClick, strong, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(LINK_BASE, strong ? 'font-semibold text-ink' : 'font-medium text-slate')}
    >
      {children}
    </button>
  );
}
