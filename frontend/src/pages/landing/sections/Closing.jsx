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
                  Admin login
                </Button>
                <Button
                  variant="ghost"
                  size="lg"
                  className="text-white/70 hover:bg-white/10 hover:text-white"
                  onClick={() => navigate('/support-desk/login')}
                >
                  Support login
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
            <FooterAction onClick={() => navigate('/admin/login')}>Admin login</FooterAction>
            <FooterAction onClick={() => navigate('/support-desk/login')}>Support login</FooterAction>
            <FooterAction onClick={() => navigate('/forgot-mpin')}>Forgot MPIN</FooterAction>
          </FooterColumn>

          <FooterColumn title="Product">
            {NAV_LINKS.map((link) => (
              <a key={link.id} href={`#${link.id}`} className={LINK}>{link.label}</a>
            ))}
          </FooterColumn>

          <FooterColumn title="Contact">
            {/* Support lives inside the member app, so this routes into it
                rather than pointing at a page that does not exist. Email,
                phone and social links come from configuration and render
                only when set: no placeholder addresses, no dead links. */}
            <FooterAction onClick={() => navigate('/signin')}>Help &amp; support</FooterAction>
            {CONTACT.email && <a href={`mailto:${CONTACT.email}`} className={LINK}>{CONTACT.email}</a>}
            {CONTACT.phone && <a href={`tel:${CONTACT.phone.replace(/\s/g, '')}`} className={LINK}>{CONTACT.phone}</a>}
            {SOCIALS.length > 0 && (
              <div className="flex gap-2 pt-1">
                {SOCIALS.map((social) => (
                  <a
                    key={social.key}
                    href={social.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={social.label}
                    className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-canvas text-slate transition-all duration-base ease-glide hover:-translate-y-px hover:text-ink"
                  >
                    <social.Icon />
                  </a>
                ))}
              </div>
            )}
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

/* ── Contact and social, from configuration ─────────────────────────── */

const env = import.meta.env;
const CONTACT = {
  email: (env.VITE_SUPPORT_EMAIL || '').trim(),
  phone: (env.VITE_SUPPORT_PHONE || '').trim(),
};

/** An http(s) URL, or '' - anything else is treated as not configured. */
function safeUrl(value) {
  const url = (value || '').trim();
  return /^https?:\/\/\S+$/i.test(url) ? url : '';
}

function Svg({ d }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true"><path d={d} /></svg>
  );
}

const SOCIALS = [
  { key: 'x', label: 'CashU on X', url: safeUrl(env.VITE_SOCIAL_X),
    Icon: () => <Svg d="M17.8 3h3.1l-6.8 7.7 8 10.3h-6.3l-4.9-6.4L5.3 21H2.2l7.3-8.3L1.8 3h6.4l4.4 5.9L17.8 3zm-1.1 16.2h1.7L7.4 4.7H5.6l11.1 14.5z" /> },
  { key: 'linkedin', label: 'CashU on LinkedIn', url: safeUrl(env.VITE_SOCIAL_LINKEDIN),
    Icon: () => <Svg d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.75h4v11H3v-11zm6.5 0h3.8v1.5h.1c.5-1 1.8-1.9 3.7-1.9 4 0 4.7 2.6 4.7 6v5.4h-4v-4.8c0-1.2 0-2.6-1.6-2.6s-1.8 1.2-1.8 2.5v4.9h-4v-11z" /> },
  { key: 'instagram', label: 'CashU on Instagram', url: safeUrl(env.VITE_SOCIAL_INSTAGRAM),
    Icon: () => <Svg d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 8.2a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4zM17.3 5.5a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4zM12 2.5c-2.6 0-2.9 0-3.9.1-3.5.2-5.4 2.1-5.6 5.6C2.5 9.1 2.5 9.4 2.5 12s0 2.9.1 3.9c.2 3.5 2.1 5.4 5.6 5.6 1 .1 1.3.1 3.9.1s2.9 0 3.9-.1c3.5-.2 5.4-2.1 5.6-5.6.1-1 .1-1.3.1-3.9s0-2.9-.1-3.9c-.2-3.5-2.1-5.4-5.6-5.6-1-.1-1.3-.1-3.9-.1z" /> },
  { key: 'youtube', label: 'CashU on YouTube', url: safeUrl(env.VITE_SOCIAL_YOUTUBE),
    Icon: () => <Svg d="M21.6 7.2a2.5 2.5 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.5 2.5 0 0 0 2.4 7.2 26 26 0 0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.8 1.8c1.6.4 7.8.4 7.8.4s6.2 0 7.8-.4a2.5 2.5 0 0 0 1.8-1.8A26 26 0 0 0 22 12a26 26 0 0 0-.4-4.8zM10 15V9l5.2 3L10 15z" /> },
].filter((social) => social.url);

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
