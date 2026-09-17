import { Component } from 'react';

/**
 * Catches render-time crashes so one broken screen does not blank the app.
 *
 * Without this, any exception thrown during render unmounts the entire React
 * tree and leaves a white page with nothing in the UI to diagnose from — the
 * error exists only in the console, which most people never open. A boundary
 * turns that into a readable message, keeps the rest of the app reachable, and
 * shows the actual error in development where it is useful.
 *
 * Must be a class: `getDerivedStateFromError` has no hook equivalent.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Still log it — the boundary is for the user, the console is for us.
    console.error('[CashU] Render error:', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const isDev = import.meta.env?.DEV;

    return (
      <div className="grid min-h-[60vh] place-items-center px-6 py-12">
        <div className="w-full max-w-lg text-center">
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-red-50 text-alert">
            <svg
              viewBox="0 0 24 24"
              className="h-7 w-7"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7.5v5.5M12 16.5h.01" strokeLinecap="round" />
            </svg>
          </div>

          <h1 className="mt-5 text-xl font-bold text-ink">This screen hit a problem</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate">
            Something went wrong while loading this page. Your account and your
            money are unaffected.
          </p>

          {/* The actual error, in development only. In production this would
              leak internals to a user who cannot act on them. */}
          {isDev && (
            <pre className="mt-5 overflow-x-auto rounded-xl bg-mist p-4 text-left text-2xs leading-relaxed text-alert">
              {error?.message || String(error)}
            </pre>
          )}

          <div className="mt-6 flex flex-wrap justify-center gap-2.5">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="h-11 rounded-xl bg-mint px-5 text-sm font-semibold text-ink shadow-mint transition hover:bg-mint-400"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => {
                window.location.href = '/home';
              }}
              className="h-11 rounded-xl border border-line bg-canvas px-5 text-sm font-medium text-ink transition hover:bg-mist"
            >
              Back to dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }
}
