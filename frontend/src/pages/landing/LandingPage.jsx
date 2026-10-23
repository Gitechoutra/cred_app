import { useEffect } from 'react';
import { MotionConfig } from 'motion/react';

import { Nav } from './sections/Nav';
import { Hero } from './sections/Hero';
import { BankMarquee } from './sections/BankMarquee';
import { Features } from './sections/Features';
import { HowItWorks } from './sections/HowItWorks';
import { Security } from './sections/Security';
import { Faq } from './sections/Faq';
import { FinalCta, Footer } from './sections/Closing';
import './landing.css';

/**
 * Public marketing page shown at "/" to signed-out visitors.
 *
 * White canvas, one mint accent, and a product visual that is the actual
 * product. Everything arrives once and then settles; the only things that keep
 * moving are the background orbs and the issuer marquee. A page that fidgets
 * reads as unserious, and this one asks people to trust it with credit cards.
 *
 * `reducedMotion="user"` makes every motion component honour the OS setting;
 * the CSS animations are covered by the global reduced-motion block.
 */
export function LandingPage() {
  useEffect(() => {
    const prev = document.title;
    document.title = 'CashU — Every card. Every EMI. One view.';
    // Smooth anchor scrolling is already global (styles/index.css).
    return () => { document.title = prev; };
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <div className="lp lp-grain min-h-screen font-sans antialiased">
        <a
          href="#features"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-full focus:bg-canvas focus:px-4 focus:py-2 focus:text-ink focus:shadow-lift"
        >
          Skip to content
        </a>
        <Nav />
        <main>
          <Hero />
          <BankMarquee />
          <Features />
          <HowItWorks />
          <Security />
          <Faq />
          <FinalCta />
        </main>
        <Footer />
      </div>
    </MotionConfig>
  );
}

export default LandingPage;
