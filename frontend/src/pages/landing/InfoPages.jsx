import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { MotionConfig } from 'motion/react';

import { CONTACT, Footer } from './sections/Closing';
import { Nav } from './sections/Nav';
import { Container, FadeIn } from './sections/shared';
import './landing.css';

/**
 * The footer's pages: About, Contact, Help & Support, Privacy and Terms.
 *
 * Privacy and Terms describe how the app actually behaves - every statement
 * is something the code enforces - and say plainly that they are summaries.
 * The binding legal documents are CashU's to issue; this page does not invent
 * them.
 */
function InfoPage({ title, intro, children, docTitle }) {
  useEffect(() => {
    const prev = document.title;
    document.title = `${docTitle || title} — CashU`;
    window.scrollTo(0, 0);
    return () => { document.title = prev; };
  }, [title, docTitle]);

  return (
    <MotionConfig reducedMotion="user">
      <div className="lp min-h-screen font-sans antialiased">
        <Nav />
        <main>
          <section className="relative border-b border-line bg-[radial-gradient(ellipse_at_top,#EEF1F4_0%,#FFFFFF_70%)]">
            <Container className="py-14 lg:py-20">
              <FadeIn>
                <p className="text-2xs font-bold uppercase tracking-[0.16em] text-slate">CashU</p>
                <h1 className="mt-3 text-4xl font-bold tracking-tight text-ink sm:text-5xl">{title}</h1>
                {intro && <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate">{intro}</p>}
              </FadeIn>
            </Container>
          </section>
          <Container className="py-12 lg:py-16">
            <div className="max-w-3xl space-y-8">{children}</div>
          </Container>
        </main>
        <Footer />
      </div>
    </MotionConfig>
  );
}

function Block({ title, children }) {
  return (
    <FadeIn>
      <section>
        <h2 className="text-lg font-bold text-ink">{title}</h2>
        <div className="mt-2 space-y-2 text-sm leading-relaxed text-slate">{children}</div>
      </section>
    </FadeIn>
  );
}

function SummaryNotice({ what }) {
  return (
    <div className="rounded-2xl border border-[#D5DBE1] bg-[linear-gradient(180deg,#FFFFFF,#F1F3F6)] p-4 text-sm leading-relaxed text-ink">
      <span className="font-semibold">This is a plain-language summary of how the app works.</span>{' '}
      It is not the formal {what}, which CashU will publish on this page. Where
      the two differ, the formal {what} will apply.
    </div>
  );
}

const linkClass = 'font-semibold text-ink underline underline-offset-2 hover:text-ink/70';

export function AboutPage() {
  return (
    <InfoPage
      title="About CashU"
      intro="One dashboard for every credit card and EMI you hold - limits, balances, due dates and payments in one clear view."
    >
      <Block title="What CashU does">
        <p>
          Credit cards from different banks live in different apps. CashU brings
          them together: add your cards, see your total limit and what you owe,
          track utilisation, get reminded before every due date, and keep your
          payment history in one record.
        </p>
        <p>
          Customers can also apply for a CashU credit line, with a limit worked
          out from their salary and credit bureau score, and track loan EMIs
          alongside their cards.
        </p>
      </Block>
      <Block title="What CashU is not">
        <p>
          CashU is a technology platform that works with licensed payment and
          lending partners. It is not a bank, does not issue credit cards and does
          not hold customer funds.
        </p>
      </Block>
      <Block title="How we build it">
        <p>
          Card numbers are tokenised under RBI Card-on-File rules and never stored.
          Customers, administrators and support agents each sign in through their
          own portal, and what each role can see and do is enforced by the server.
        </p>
      </Block>
    </InfoPage>
  );
}

export function ContactPage() {
  return (
    <InfoPage title="Contact" intro="The quickest way to reach us depends on what you need.">
      <Block title="Customers">
        <p>
          Signed in? Open <strong>Help &amp; support</strong> in the app and raise a
          ticket. It reaches our support desk with your account attached, so you do
          not have to repeat your details, and you can follow every reply there.
        </p>
        <p><Link to="/signin" className={linkClass}>Sign in to raise a ticket</Link></p>
      </Block>
      {(CONTACT.email || CONTACT.phone) && (
        <Block title="Email and phone">
          {CONTACT.email && (
            <p>Email: <a href={`mailto:${CONTACT.email}`} className={linkClass}>{CONTACT.email}</a></p>
          )}
          {CONTACT.phone && (
            <p>Phone: <a href={`tel:${CONTACT.phone.replace(/\s/g, '')}`} className={linkClass}>{CONTACT.phone}</a></p>
          )}
        </Block>
      )}
      <Block title="Never share these">
        <p>
          CashU will never ask for your full card number, CVV, card PIN, MPIN, OTP or
          net banking password - not by phone, email, chat or in a support ticket.
        </p>
      </Block>
    </InfoPage>
  );
}

export function HelpPage() {
  return (
    <InfoPage title="Help & Support" intro="Answers to common questions, and how to get a person when you need one.">
      <Block title="Can't sign in?">
        <p>
          Use <Link to="/forgot-mpin" className={linkClass}>Forgot MPIN</Link> to reset it with an OTP to your
          registered mobile. Resetting signs you out on every device. Staff reset
          from their own portal&apos;s sign-in screen.
        </p>
      </Block>
      <Block title="Signing in to the right portal">
        <p>
          Customers use <Link to="/signin" className={linkClass}>User Login</Link>. Administrators use{' '}
          <Link to="/admin/login" className={linkClass}>Admin Login</Link>, and support agents use{' '}
          <Link to="/support-desk/login" className={linkClass}>Customer Support Login</Link>. Each portal
          only admits its own accounts and will point you to the right one.
        </p>
      </Block>
      <Block title="A problem with a card, payment or bill">
        <p>
          Sign in and open <strong>Help &amp; support</strong> to raise a ticket.
          A failed payment can be sent to support straight from its receipt, with
          the details attached. You can follow the ticket from Open to In progress
          to Resolved in the app.
        </p>
      </Block>
      <Block title="Common questions">
        <p>See the <a href="/#faq" className={linkClass}>FAQ</a> on the home page.</p>
      </Block>
    </InfoPage>
  );
}

export function PrivacyPage() {
  return (
    <InfoPage docTitle="Privacy Policy" title="Privacy" intro="What CashU keeps about you, why, and who can see it.">
      <SummaryNotice what="Privacy Policy" />
      <Block title="Card details">
        <p>
          Card numbers are tokenised with a licensed partner. CashU keeps the token
          and the last four digits - never the full number, the CVV or the PIN.
          Cards you add by hand hold only the bank, the last four digits and the
          figures you type, which are always shown as entered by you.
        </p>
      </Block>
      <Block title="Identity and sign-in">
        <p>
          Your PAN and similar identity numbers are stored encrypted. Your MPIN and
          one-time passwords are stored only as salted hashes, so nobody at CashU
          can read them. Every sign-in is logged, and you can sign out all devices
          from Security.
        </p>
      </Block>
      <Block title="Credit bureau checks">
        <p>
          Your credit score is fetched from a bureau only after you give consent on
          screen, and the record keeps when you consented.
        </p>
      </Block>
      <Block title="Who can see your data">
        <p>
          Support agents see a masked profile: your name, the last digits of your
          phone number and the status of your cards and payments. They cannot see
          identity numbers, card numbers or your MPIN. Administrators who can see
          more do so through audited screens, and every view is recorded.
        </p>
      </Block>
      <Block title="Your rights">
        <p>
          Personal data is handled under India&apos;s Digital Personal Data
          Protection Act, 2023. To ask about your data, raise a ticket from Help
          &amp; support in the app.
        </p>
      </Block>
    </InfoPage>
  );
}

export function TermsPage() {
  return (
    <InfoPage title="Terms" intro="The main rules of using CashU, in plain language.">
      <SummaryNotice what="Terms of Service" />
      <Block title="Your account">
        <p>
          You sign in with your mobile number and a 6-digit MPIN. Keep your MPIN to
          yourself; CashU will never ask for it. Repeated wrong attempts lock the
          account for a while to protect it.
        </p>
      </Block>
      <Block title="Card figures">
        <p>
          Limits on tokenised cards are set by CashU. Figures on cards you add by
          hand are yours, labelled &ldquo;User-entered - Not Bank Verified&rdquo;,
          and are not confirmed by your bank. Check your bank&apos;s statement for
          the amount you actually owe.
        </p>
      </Block>
      <Block title="Payments and fees">
        <p>
          Any fee is shown before you confirm a payment, never added afterwards.
          A payment counts as successful only when the payment gateway confirms
          it - not when the app says it was sent.
        </p>
      </Block>
      <Block title="What CashU is">
        <p>
          CashU is a technology platform working with licensed partners. It is not a
          bank, does not issue credit cards and does not hold your money.
        </p>
      </Block>
    </InfoPage>
  );
}
