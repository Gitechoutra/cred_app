import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AnimatePresence, motion, useMotionValueEvent, useScroll, useSpring,
} from 'motion/react';

import { Logo } from '../../../components/layout/AppShell';
import { Button, cx } from '../../../components/ui';
import { EASE } from './shared';

export const NAV_LINKS = [
  { label: 'Features', id: 'features' },
  { label: 'How it works', id: 'how-it-works' },
  { label: 'Security', id: 'security' },
  { label: 'FAQ', id: 'faq' },
];

/**
 * Sticky top bar.
 *
 * Both doors stay in it at every width: customers and staff sign in through
 * different screens, and nobody should have to scroll to find theirs. Below
 * `sm` they move into the sheet so the bar keeps its shape at 320px.
 */
export function Nav() {
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const { scrollY, scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 140, damping: 30, mass: 0.4 });
  useMotionValueEvent(scrollY, 'change', (y) => setScrolled(y > 8));

  // An open sheet over a scrolling page is disorienting, and on iOS the body
  // scrolls behind the overlay rather than the overlay itself.
  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  const go = (path) => {
    setMenuOpen(false);
    navigate(path);
  };

  return (
    <header
      className={cx(
        'sticky top-0 z-50 transition-all duration-slow ease-glide',
        scrolled || menuOpen
          ? 'border-b border-line bg-canvas/80 shadow-card backdrop-blur-xl'
          : 'border-b border-transparent bg-canvas/50 backdrop-blur-sm',
      )}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3.5 sm:px-6 lg:px-8">
        <a href="#top" className="flex flex-1 items-center gap-2.5" aria-label="CashU, back to top">
          <Logo className="h-9 w-9" />
          <span>
            <span className="block text-base font-bold leading-none tracking-tight text-ink">CashU</span>
            <span className="mt-1 hidden text-2xs text-slate sm:block">Credit &amp; EMI hub</span>
          </span>
        </a>

        <nav aria-label="Sections" className="mr-2 hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="group relative rounded-lg px-3 py-2 text-xs font-medium text-slate transition-colors duration-base hover:text-ink"
            >
              {item.label}
              <span
                aria-hidden="true"
                className="absolute inset-x-3 bottom-1 h-px origin-center scale-x-0 bg-mint transition-transform duration-base ease-glide group-hover:scale-x-100"
              />
            </a>
          ))}
        </nav>

        <button
          type="button"
          onClick={() => go('/admin/login')}
          className="hidden rounded-xl border border-line px-3.5 py-2 text-xs font-semibold text-slate transition-all duration-base ease-glide hover:-translate-y-px hover:border-ink/20 hover:text-ink sm:block"
        >
          Admin login
        </button>

        <div className="hidden sm:block">
          <Button variant="mint" size="sm" onClick={() => go('/signin')}>
            User login
          </Button>
        </div>

        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
          aria-controls="lp-mobile-menu"
          className="grid h-10 w-10 place-items-center rounded-xl border border-line text-ink transition-colors duration-base hover:bg-mist sm:hidden"
        >
          <span className="relative block h-4 w-5" aria-hidden="true">
            <span
              className={cx(
                'absolute left-0 block h-0.5 w-5 rounded bg-current transition-all duration-base ease-glide',
                menuOpen ? 'top-1/2 -translate-y-1/2 rotate-45' : 'top-0',
              )}
            />
            <span
              className={cx(
                'absolute left-0 top-1/2 block h-0.5 w-5 -translate-y-1/2 rounded bg-current transition-all duration-base ease-glide',
                menuOpen && 'scale-x-0 opacity-0',
              )}
            />
            <span
              className={cx(
                'absolute left-0 block h-0.5 w-5 rounded bg-current transition-all duration-base ease-glide',
                menuOpen ? 'top-1/2 -translate-y-1/2 -rotate-45' : 'bottom-0',
              )}
            />
          </span>
        </button>
      </div>

      {/* Reading progress. Mint, one pixel, along the bar's bottom edge. */}
      <motion.span
        aria-hidden="true"
        className="absolute inset-x-0 bottom-[-1px] h-px origin-left bg-mint"
        style={{ scaleX: progress }}
      />

      <AnimatePresence>
        {menuOpen && (
          <motion.div
            key="sheet"
            id="lp-mobile-menu"
            className="sm:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <button
              type="button"
              aria-label="Close menu"
              onClick={() => setMenuOpen(false)}
              className="fixed inset-0 top-[4.25rem] z-40 cursor-default bg-ink/20 backdrop-blur-sm"
            />
            <motion.div
              className="relative z-50 border-t border-line bg-canvas px-4 pb-5 pt-3 shadow-lift"
              initial={{ y: -12 }}
              animate={{ y: 0 }}
              exit={{ y: -12 }}
              transition={{ duration: 0.28, ease: EASE }}
            >
              <nav aria-label="Sections" className="space-y-1">
                {NAV_LINKS.map((item, index) => (
                  <motion.a
                    key={item.id}
                    href={`#${item.id}`}
                    onClick={() => setMenuOpen(false)}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3, ease: EASE, delay: 0.04 + index * 0.05 }}
                    className="block rounded-xl px-3 py-3 text-sm font-medium text-ink transition-colors duration-base hover:bg-mist"
                  >
                    {item.label}
                  </motion.a>
                ))}
              </nav>

              <div className="mt-4 space-y-2 border-t border-line pt-4">
                <Button variant="mint" size="lg" full onClick={() => go('/signin')}>
                  User login
                </Button>
                <Button variant="outline" size="lg" full onClick={() => go('/admin/login')}>
                  Admin login
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
