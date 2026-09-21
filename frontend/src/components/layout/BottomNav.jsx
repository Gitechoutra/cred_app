import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

import { cx } from '../ui';

/**
 * Bottom navigation, in the shape people already know from PhonePe.
 *
 * Two forms, one component. Below `sm` it is a full-width bar welded to the
 * bottom edge with safe-area padding, because that is where a thumb lives. From
 * `sm` up it lifts into a centred floating pill - a full-width bar stretched
 * across a 27" monitor reads as a website footer, not as navigation.
 *
 * The bar is `fixed`, so every shell using it must reserve space at the bottom
 * of its scroll container or the last row of content hides underneath.
 */
export function BottomNav({ items, children }) {
  return (
    <nav
      aria-label="Primary"
      /* z-40, matching the top bar. Modals and sheets sit at z-50 and must
         cover the navigation - a bar floating over a dialog's Approve button
         is worse than no bar at all. */
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center"
    >
      <div
        className={cx(
          'pointer-events-auto relative flex w-full items-stretch gap-0.5',
          'border-t border-line bg-canvas px-1 pt-1.5',
          'pb-[max(0.375rem,env(safe-area-inset-bottom))]',
          'shadow-[0_-6px_28px_-16px_rgba(10,15,13,0.35)]',
          'sm:mb-5 sm:w-auto sm:gap-1 sm:rounded-2xl sm:border sm:px-2 sm:pb-2 sm:pt-2 sm:shadow-lift',
        )}
      >
        {items.map((item) => (
          <BottomNavItem key={item.to} {...item} />
        ))}
        {children}
      </div>
    </nav>
  );
}

function BottomNavItem({ to, label, icon: Icon, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cx(
          'flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5',
          'transition-colors sm:w-[4.5rem] sm:flex-none sm:px-2 sm:py-2',
          isActive ? 'bg-mint-50 text-ink' : 'text-slate hover:bg-mist hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            className={cx(
              'h-[22px] w-[22px] shrink-0 transition-colors',
              isActive && 'text-mint-700',
            )}
          />
          <span
            className={cx(
              'max-w-full truncate text-[10px] leading-none sm:text-[11px]',
              isActive ? 'font-semibold' : 'font-medium',
            )}
          >
            {label}
          </span>
        </>
      )}
    </NavLink>
  );
}

/**
 * The account slot at the right-hand end of the bar.
 *
 * Opens upward, anchored to the right edge, so it never runs off-screen and
 * never covers the bar it belongs to. Dismisses on outside click and Escape -
 * a menu you cannot close without choosing something is a trap.
 *
 * `items` are plain objects: `{ label, icon, to }` to navigate, `{ label, icon,
 * onClick }` to run something, `{ divider: true }` to separate groups, and
 * `tone: 'danger'` for sign-out.
 */
export function ProfileMenu({ name, detail, avatar, items }) {
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
    <div ref={wrapper} className="relative flex min-w-0 flex-1 sm:flex-none">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className={cx(
          'flex w-full flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5',
          'transition-colors sm:w-[4.5rem] sm:px-2 sm:py-2',
          open ? 'bg-mint-50 text-ink' : 'text-slate hover:bg-mist hover:text-ink',
        )}
      >
        <span
          className={cx(
            'grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full text-[9px] font-bold transition-colors',
            open ? 'bg-mint text-ink' : 'bg-ink text-mint',
          )}
        >
          {avatar}
        </span>
        <span
          className={cx(
            'max-w-full truncate text-[10px] leading-none sm:text-[11px]',
            open ? 'font-semibold' : 'font-medium',
          )}
        >
          Profile
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className={cx(
            'absolute bottom-full right-0 mb-2 w-60 max-w-[calc(100vw-1.5rem)]',
            'origin-bottom-right animate-scale-in rounded-2xl border border-line',
            'bg-canvas p-1.5 shadow-lift',
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
