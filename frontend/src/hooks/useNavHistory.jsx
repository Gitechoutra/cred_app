import { createContext, useCallback, useContext, useEffect, useRef } from 'react';
import { useLocation, useNavigate, useNavigationType } from 'react-router-dom';

/**
 * In-app navigation history.
 *
 * Back buttons used to do one of two things: `navigate(-1)`, which leaves the
 * app entirely when the page was opened from a link, or `navigate('/credit')`,
 * which pushes a *new* entry - so pressing the browser's back button afterwards
 * returns to the screen the user just left, and two screens that link to each
 * other that way become a loop.
 *
 * This tracks what each entry in the tab's history actually is, using the index
 * React Router already stores in `history.state`. That gives two operations:
 *
 *   back()          the real previous screen when there is one inside the app,
 *                   and a sensible parent only when there is not.
 *   returnTo(path)  finish a flow by going *back* to an earlier screen, so the
 *                   completed steps drop off the stack instead of piling up
 *                   behind a second copy of the screen the user started from.
 *
 * Nothing here pushes or rewrites entries, so the browser's own back and
 * forward buttons keep working exactly as they would without it. Persisted per
 * tab in sessionStorage, because the history it describes survives a reload.
 */

const STORE = 'cashu.nav.entries';
const NavHistoryContext = createContext(null);

function currentIndex() {
  try {
    return window.history.state?.idx ?? 0;
  } catch {
    return 0;
  }
}

function load() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(STORE));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function save(entries) {
  try {
    sessionStorage.setItem(STORE, JSON.stringify(entries));
  } catch {
    /* Private browsing. Back still works; returnTo just finds less. */
  }
}

export function NavHistoryProvider({ children }) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const entries = useRef(load());

  useEffect(() => {
    const index = currentIndex();
    const list = entries.current;

    // A push discards everything that was forward of the new entry - the same
    // thing the browser does to its own stack.
    if (navigationType === 'PUSH') list.length = index;
    list[index] = location.pathname;
    save(list);
  }, [location.key, location.pathname, navigationType]);

  return (
    <NavHistoryContext.Provider value={entries}>
      {children}
    </NavHistoryContext.Provider>
  );
}

/**
 * A back handler that returns to the screen the user actually came from.
 *
 * `fallback` is used only when there is no earlier screen in this tab - the
 * page was opened from a link or a bookmark - and should be the page's logical
 * parent, not the dashboard.
 */
export function useBack(fallback = '/home') {
  const navigate = useNavigate();

  return useCallback(() => {
    if (currentIndex() > 0) navigate(-1);
    else navigate(fallback, { replace: true });
  }, [navigate, fallback]);
}

/**
 * Finish a flow by going back to `path` if it is already behind us, rather
 * than pushing another copy of it.
 *
 * Only an exact path match counts. When `path` is not in the history - the flow
 * was entered directly - the current entry is replaced, so the completed step
 * is still not left behind for the back button to land on.
 */
export function useReturnTo() {
  const navigate = useNavigate();
  const entries = useContext(NavHistoryContext);

  return useCallback((path, options = {}) => {
    const index = currentIndex();
    const list = entries?.current || [];

    for (let earlier = index - 1; earlier >= 0; earlier -= 1) {
      if (list[earlier] === path) {
        navigate(earlier - index);
        return;
      }
    }
    navigate(path, { replace: true, ...options });
  }, [entries, navigate]);
}
