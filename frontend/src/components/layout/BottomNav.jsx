import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

import { cx } from '../ui';
import { IconChevron, IconSearch, IconUser } from './AppShell';

/**
 * Floating Rounded Bottom Navigation.
 *
 * 5 items:
 * 1. Home
 * 2. Cards
 * 3. Scanner (highlighted as active/selected with subtle premium accent)
 * 4. Search (triggers quick-search modal)
 * 5. History
 *
 * Minimalist, floating rounded style with clean typography and spacing across all viewports.
 */

export function BottomNav({ items, children }) {
  const [searchOpen, setSearchOpen] = useState(false);

  return (
    <>
      <nav
        aria-label="Primary"
        className={cx(
          'pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-4',
          // max() keeps the existing 2.5 spacing on an ordinary screen and
          // grows it on a notched phone, where a flat padding leaves the bar
          // sitting under the home indicator.
          'pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:pb-6',
        )}
      >
        <div
          className={cx(
            'pointer-events-auto relative flex w-full max-w-md items-center justify-between gap-1',
            'rounded-2xl sm:rounded-3xl border border-line/80 bg-canvas/92 backdrop-blur-2xl px-2 py-1.5',
            'shadow-[0_12px_36px_-10px_rgba(10,15,13,0.18),0_2px_8px_rgba(10,15,13,0.04)]',
            'sm:px-3 sm:py-2',
            'transition-all duration-base ease-glide',
          )}
        >
          {items.map((item) =>
            item.id === 'search' ? (
              <SearchNavItem
                key="search"
                {...item}
                onClick={() => setSearchOpen(true)}
              />
            ) : (
              <BottomNavItem key={item.to} {...item} />
            ),
          )}
          {children}
        </div>
      </nav>

      {searchOpen && <SearchModal onClose={() => setSearchOpen(false)} />}
    </>
  );
}

function BottomNavItem({ to, label, icon: Icon, end, isScanner }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => {
        // Highlight Scanner as the active/selected tab with a subtle premium accent,
        // while keeping the other icons minimal and clean.
        const highlighted = isScanner || isActive;

        return cx(
          'group relative flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5',
          'transition-all duration-base ease-glide active:scale-95 sm:px-2 sm:py-2',
          isScanner
            ? 'bg-mint-50/95 text-ink shadow-[inset_0_0_0_1px_rgba(0,245,184,0.35),0_2px_10px_rgba(0,245,184,0.18)]'
            : isActive
              ? 'text-ink font-semibold'
              : 'text-slate hover:bg-mist/70 hover:text-ink',
        );
      }}
    >
      {({ isActive }) => {
        const highlighted = isScanner;

        return (
          <>
            <Icon
              className={cx(
                'h-[21px] w-[21px] shrink-0 transition-all duration-base ease-glide',
                highlighted
                  ? 'text-mint-700 animate-pop scale-105'
                  : 'text-slate group-hover:scale-105 group-hover:text-ink',
              )}
            />
            <span
              className={cx(
                'max-w-full truncate text-[10.5px] sm:text-[11px] leading-none tracking-tight text-center',
                highlighted
                  ? 'font-bold text-ink'
                  : 'font-medium text-slate group-hover:text-ink',
              )}
            >
              {label}
            </span>
            {highlighted && (
              <span
                aria-hidden="true"
                className="absolute -bottom-0.5 sm:bottom-0.5 left-1/2 h-1 w-3.5 -translate-x-1/2 rounded-full bg-mint-600 shadow-[0_0_8px_rgba(0,245,184,0.6)]"
              />
            )}
          </>
        );
      }}
    </NavLink>
  );
}

function SearchNavItem({ label, icon: Icon, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Search"
      className={cx(
        'group relative flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5',
        'transition-all duration-base ease-glide active:scale-95 sm:px-2 sm:py-2',
        'text-slate hover:bg-mist/70 hover:text-ink',
      )}
    >
      <Icon className="h-[21px] w-[21px] shrink-0 text-slate transition-all duration-base ease-glide group-hover:scale-105 group-hover:text-ink" />
      <span className="max-w-full truncate text-[10.5px] sm:text-[11px] leading-none tracking-tight font-medium text-slate group-hover:text-ink">
        {label}
      </span>
    </button>
  );
}

/**
 * Account slot menu for header / shell.
 */
export function ProfileMenu({ name, detail, avatar, items, placement = 'top' }) {
  // Upward by default. This menu hangs off a bar pinned to the bottom of the
  // viewport, so opening downward puts it off-screen - which is exactly what
  // happened: the admin menu rendered below the fold and the sign-out item was
  // unreachable. `placement="bottom"` remains available for a top-anchored bar.

  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const wrapper = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    function onPointerDown(event) {
      if (wrapper.current && !wrapper.current.contains(event.target)) setOpen(false);
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') setOpen(false);
    }

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={wrapper} className="relative flex shrink-0 items-center">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className={cx(
          'group relative flex items-center justify-center rounded-xl p-1',
          'transition-all duration-base ease-glide active:scale-95',
          open ? 'ring-2 ring-mint' : 'hover:opacity-85',
        )}
      >
        <span
          className={cx(
            'grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold transition-all duration-base ease-glide',
            open
              ? 'bg-mint-500 text-ink shadow-sm ring-1 ring-mint-300'
              : 'bg-ink text-mint ring-1 ring-line',
          )}
        >
          {avatar}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className={cx(
            'absolute right-0 z-50 w-64 max-w-[calc(100vw-1.5rem)]',
            placement === 'top'
              ? 'bottom-full mb-3 origin-bottom-right'
              : 'top-full mt-2.5 origin-top-right',
            'animate-scale-in rounded-2xl border border-line/80',
            'bg-canvas/95 backdrop-blur-xl p-2 shadow-[0_16px_40px_-12px_rgba(10,15,13,0.2)]',
          )}
        >
          <div className="flex items-center gap-2.5 px-2.5 py-2.5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-xs font-bold text-mint">
              {avatar}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">{name || 'Member'}</p>
              {detail && <p className="money truncate text-2xs text-slate">{detail}</p>}
            </div>
          </div>

          <div className="my-1 h-px bg-line" />

          {items.map((item, index) =>
            item.divider ? (
              <div key={`divider-${index}`} className="my-1 h-px bg-line" />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  if (item.onClick) item.onClick();
                  else navigate(item.to);
                }}
                className={cx(
                  'flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left',
                  'text-sm font-medium transition-colors',
                  item.tone === 'danger'
                    ? 'text-alert hover:bg-red-50'
                    : 'text-ink hover:bg-mist',
                )}
              >
                {item.icon && (
                  <item.icon
                    className={cx(
                      'h-[18px] w-[18px] shrink-0',
                      item.tone === 'danger' ? 'text-alert' : 'text-slate',
                    )}
                  />
                )}
                <span className="truncate">{item.label}</span>
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Universal quick-search modal for CashU.
 */
function SearchModal({ onClose }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();

    function onKeyDown(event) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const SEARCH_ITEMS = [
    { title: 'My Credit Line', hint: 'Limit, spends and statements', to: '/credit' },
    { title: 'Apply for Credit', hint: 'Open a new credit line', to: '/credit/apply' },
    { title: 'Pay Card Bill', hint: 'Settle your statement', to: '/credit/pay' },
    { title: 'Statements', hint: 'Monthly credit card bills', to: '/credit/statements' },
    { title: 'Credit Cards', hint: 'Manage linked cards & limits', to: '/cards' },
    { title: 'Scan & Pay QR', hint: 'Scan UPI QR code', to: '/scan' },
    { title: 'EMIs & Installments', hint: 'View loan schedules', to: '/emi' },
    { title: 'Bank Accounts', hint: 'Verified bank accounts', to: '/banks' },
    { title: 'Transaction History', hint: 'Statements and receipts', to: '/transactions' },
    { title: 'Member Profile', hint: 'KYC & personal information', to: '/profile' },
    { title: 'Security & MPIN', hint: 'Manage devices & PIN', to: '/security' },
    { title: 'Help & Support', hint: '24/7 dedicated support', to: '/support' },
  ];

  const filtered = query.trim()
    ? SEARCH_ITEMS.filter(
        (item) =>
          item.title.toLowerCase().includes(query.toLowerCase()) ||
          item.hint.toLowerCase().includes(query.toLowerCase()),
      )
    : SEARCH_ITEMS;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16 sm:pt-24 bg-ink/40 backdrop-blur-sm animate-fade-up"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg overflow-hidden rounded-3xl border border-line bg-canvas p-4 shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line pb-3.5">
          <IconSearch className="h-5 w-5 text-mint-700 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search cards, EMIs, transactions, services..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-transparent text-sm font-medium text-ink placeholder:text-slate outline-none"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="text-xs font-semibold text-slate hover:text-ink px-1.5 py-0.5 rounded"
            >
              Clear
            </button>
          )}
          <span className="hidden sm:inline-block rounded bg-mist px-1.5 py-0.5 text-[10px] font-semibold text-slate">
            ESC
          </span>
        </div>

        <div className="mt-3 max-h-80 overflow-y-auto space-y-1">
          {filtered.length > 0 ? (
            filtered.map((item) => (
              <button
                key={item.to}
                type="button"
                onClick={() => {
                  onClose();
                  navigate(item.to);
                }}
                className="group flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left hover:bg-mist/70 transition-colors"
              >
                <div>
                  <p className="text-sm font-semibold text-ink group-hover:text-mint-800">
                    {item.title}
                  </p>
                  <p className="text-2xs text-slate">{item.hint}</p>
                </div>
                <IconChevron className="h-4 w-4 text-slate-light group-hover:translate-x-0.5 group-hover:text-ink transition-transform" />
              </button>
            ))
          ) : (
            <p className="py-8 text-center text-xs text-slate">
              No features match &ldquo;{query}&rdquo;
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
