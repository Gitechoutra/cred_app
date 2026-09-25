import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import { ErrorCard, JourneySteps, friendlyError } from '../../components/credit/CreditUI';
import { useFetch } from '../../hooks/useProfile';
import { useSessionDraft } from '../../hooks/useSessionDraft';
import { money } from '../../utils/format';

/**
 * Purpose of credit. Mandatory, and a real gate rather than a form field.
 *
 * A dropdown, as the product spec asks, built as a proper listbox rather than a
 * native <select>: the native one cannot show an icon per option or a
 * description, and renders differently on every platform. It behaves like one
 * anyway - arrow keys, Home/End, Enter, Escape, and a click outside closes it.
 *
 * The options come from the server, including which one requires a note, so the
 * list cannot drift from what the backend will accept. The choice is validated
 * here for a fast answer and again by the server, which is the one that counts.
 *
 * Declaring is one-off: the server refuses a second declaration. A holder who
 * returns here afterwards - with the back button, say - is shown what they chose
 * rather than a form that can only fail.
 */

const ICONS = {
  EDUCATION: 'M3 8l9-4 9 4-9 4-9-4zm4 2v5c0 1.5 2.5 3 5 3s5-1.5 5-3v-5',
  MEDICAL: 'M12 6v12M6 12h12',
  SHOPPING: 'M6 7h12l-1 12H7L6 7zm3 0a3 3 0 016 0',
  TRAVEL: 'M2 13l20-7-7 20-3-8-8-3z',
  BUSINESS: 'M4 8h16v12H4V8zm5 0V5h6v3',
  BILLS: 'M6 3h12v18l-3-2-3 2-3-2-3 2V3zm3 5h6m-6 4h6',
  EMERGENCY: 'M12 3l9 17H3l9-17zm0 6v5m0 3v.5',
  OTHER: 'M6 12h.5m5.5 0h.5m5.5 0h.5',
};

const HINTS = {
  EDUCATION: 'Fees, courses, books',
  MEDICAL: 'Treatment, medicines, insurance',
  SHOPPING: 'Everyday and big purchases',
  TRAVEL: 'Tickets, stays, trips',
  BUSINESS: 'Stock, tools, services',
  BILLS: 'Utilities, rent, recharges',
  EMERGENCY: 'The unexpected',
  OTHER: 'Tell us in your own words',
};

// The spec's wording for this option; the server's label is shorter.
const LABEL_OVERRIDES = { MEDICAL: 'Medical / Health' };

function PurposeIcon({ value, active }) {
  return (
    <span
      className={cx(
        'grid h-9 w-9 shrink-0 place-items-center rounded-xl transition-colors',
        active ? 'bg-mint text-ink' : 'bg-mist text-slate',
      )}
    >
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" aria-hidden="true">
        <path
          d={ICONS[value] || ICONS.OTHER}
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

function PurposeSelect({ options, value, onChange, error }) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapper = useRef(null);
  const list = useRef(null);
  const id = useId();

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (!wrapper.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('touchstart', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('touchstart', close);
    };
  }, [open]);

  // On a phone the list opens low on the screen, and its last options would sit
  // behind the fixed bottom navigation - visible, but a tap there lands on the
  // nav. Bring the whole list into view on open; its scroll margin keeps it
  // clear of the bar.
  useEffect(() => {
    if (open) list.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [open]);

  useEffect(() => {
    if (open) list.current?.querySelector(`[data-index="${highlight}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [open, highlight]);

  function openList() {
    setHighlight(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  }

  function choose(index) {
    onChange(options[index].value);
    setOpen(false);
  }

  function onKeyDown(event) {
    if (!open && ['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
      event.preventDefault();
      openList();
      return;
    }
    if (!open) return;

    const last = options.length - 1;
    const moves = {
      ArrowDown: () => setHighlight((h) => Math.min(last, h + 1)),
      ArrowUp: () => setHighlight((h) => Math.max(0, h - 1)),
      Home: () => setHighlight(0),
      End: () => setHighlight(last),
      Enter: () => choose(highlight),
      ' ': () => choose(highlight),
      Escape: () => setOpen(false),
      Tab: () => setOpen(false),
    };
    if (moves[event.key]) {
      if (event.key !== 'Tab') event.preventDefault();
      moves[event.key]();
    }
  }

  return (
    <div ref={wrapper} className="relative">
      <label id={`${id}-label`} className="mb-1.5 block text-sm font-medium text-ink">
        Purpose of credit
      </label>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label`}
        aria-controls={`${id}-list`}
        aria-invalid={Boolean(error)}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        className={cx(
          'flex min-h-[3.5rem] w-full items-center gap-3 rounded-2xl border bg-canvas px-3 py-2 text-left',
          'transition-all duration-base ease-glide',
          error
            ? 'border-alert ring-2 ring-alert/15'
            : open
              ? 'border-ink/40 ring-2 ring-mint/25'
              : 'border-line hover:border-ink/25',
        )}
      >
        {selected ? (
          <>
            <PurposeIcon value={selected.value} active />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-ink">{selected.label}</span>
              <span className="block truncate text-2xs text-slate">{HINTS[selected.value]}</span>
            </span>
          </>
        ) : (
          <span className="flex-1 px-1 text-sm text-slate-light">Select what you will use it for</span>
        )}
        <svg
          viewBox="0 0 20 20"
          className={cx('h-4 w-4 shrink-0 text-slate transition-transform duration-base', open && 'rotate-180')}
          fill="none"
          aria-hidden="true"
        >
          <path d="M5 7.5l5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <ul
          ref={list}
          id={`${id}-list`}
          role="listbox"
          aria-labelledby={`${id}-label`}
          aria-activedescendant={`${id}-opt-${highlight}`}
          tabIndex={-1}
          // In the page flow, not absolutely positioned. The bottom navigation
          // is fixed on every breakpoint, and an absolute list on a short page
          // hangs into the space reserved for it: its last options could not
          // be scrolled clear of the bar and a tap on them hit the nav. In flow,
          // the page grows to fit the open list.
          className="relative z-10 mt-2 max-h-72 scroll-mb-32 scroll-mt-20 animate-slide-down overflow-y-auto rounded-2xl border border-line bg-white/95 p-1.5 shadow-lift backdrop-blur-xl sm:max-h-80"
        >
          {options.map((option, index) => {
            const active = option.value === value;
            return (
              <li
                key={option.value}
                id={`${id}-opt-${index}`}
                data-index={index}
                role="option"
                aria-selected={active}
                onMouseEnter={() => setHighlight(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(index)}
                className={cx(
                  'flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2 transition-colors',
                  index === highlight ? 'bg-mist' : 'bg-transparent',
                )}
              >
                <PurposeIcon value={option.value} active={active} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{option.label}</span>
                  <span className="block truncate text-2xs text-slate">{HINTS[option.value]}</span>
                </span>
                {active && (
                  <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-mint-700" fill="none" aria-hidden="true">
                    <path d="M4.5 10.5l3.5 3.5 7.5-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="mt-1.5 animate-slide-down text-xs text-alert">{error}</p>}
    </div>
  );
}

export default function CreditPurpose() {
  const navigate = useNavigate();

  const { data: options, loading, error: optionsError, refetch: refetchOptions } = useFetch(
    () => endpoints.credit.purposes(), [],
  );
  const { data: account, loading: accountLoading, error: accountError } = useFetch(
    () => endpoints.credit.account(), [],
  );

  const [draft, update, clearDraft] = useSessionDraft('credit-purpose', { purpose: '', note: '' });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState('');

  const purposes = (options?.purposes || []).map((p) => ({
    ...p, label: LABEL_OVERRIDES[p.value] || p.label,
  }));
  const selected = purposes.find((p) => p.value === draft.purpose);
  const needsNote = Boolean(selected?.requires_note);
  const note = draft.note.trim();

  const purposeError = touched && !selected ? 'Choose what you will use this credit for.' : '';
  const noteError = touched && needsNote && note.length < 3
    ? 'Tell us in a few words - at least 3 characters.'
    : '';

  async function submit() {
    setTouched(true);
    if (!selected || (needsNote && note.length < 3) || busy) return;

    setBusy(true);
    setSubmitError('');
    try {
      await endpoints.credit.setPurpose({
        purpose: draft.purpose,
        // Only sent for the option that asks for it. The server refuses a note
        // on any other purpose, so sending one always would be a bug.
        purpose_note: needsNote ? note : undefined,
      });
      clearDraft();
      navigate('/credit/activate', { replace: true });
    } catch (err) {
      setSubmitError(friendlyError(err, 'We could not save that. Please try again.'));
      setBusy(false);
    }
  }

  if (loading || accountLoading) {
    return (
      <div className="mx-auto w-full max-w-xl">
        <PageHeader title="Purpose of credit" back="/credit" />
        <Card className="space-y-4 p-6">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </Card>
      </div>
    );
  }

  if (optionsError || (!account && accountError?.code !== 'NO_CREDIT_LINE')) {
    return (
      <div className="mx-auto w-full max-w-xl">
        <PageHeader title="Purpose of credit" back="/credit" />
        <ErrorCard error={optionsError || accountError} onRetry={refetchOptions} />
      </div>
    );
  }

  if (!account) {
    return (
      <div className="mx-auto w-full max-w-xl">
        <PageHeader title="Purpose of credit" back="/credit" />
        <Card className="p-6 text-center">
          <p className="text-base font-semibold text-ink">You do not have an approved credit line yet</p>
          <Button variant="mint" size="lg" full className="mt-5" onClick={() => navigate('/credit', { replace: true })}>
            Go to Credit
          </Button>
        </Card>
      </div>
    );
  }

  // Already declared. Show it, rather than a form the server will refuse.
  if (account.status !== 'PENDING_PURPOSE') {
    return (
      <div className="mx-auto w-full max-w-xl animate-fade-up">
        <PageHeader title="Purpose of credit" back="/credit" />
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <PurposeIcon value={account.purpose} active />
            <div className="min-w-0">
              <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Purpose recorded</p>
              <p className="truncate text-base font-semibold text-ink">
                {LABEL_OVERRIDES[account.purpose] || account.purpose_label}
              </p>
            </div>
          </div>
          {account.purpose_note && <Row label="Your note" value={account.purpose_note} className="mt-3" />}
          <Button
            variant="mint"
            size="lg"
            full
            className="mt-5"
            onClick={() => navigate(account.status === 'PENDING_ACTIVATION' ? '/credit/activate' : '/credit', { replace: true })}
          >
            {account.status === 'PENDING_ACTIVATION' ? 'Activate your card' : 'Go to my card'}
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xl animate-fade-up">
      <PageHeader
        eyebrow="Step 5 of 6"
        title="Purpose of credit"
        subtitle="Required before your card can be activated."
        back="/credit"
      />

      <JourneySteps current="PURPOSE" className="mb-5" />

      <Card className="mb-4 overflow-hidden !p-0">
        <div className="flex items-center justify-between gap-3 bg-gradient-to-br from-mint-50 via-canvas to-canvas px-5 py-4">
          <div className="min-w-0">
            <p className="text-2xs font-semibold uppercase tracking-wider text-mint-800">Approved credit limit</p>
            <p className="money mt-0.5 text-2xl font-bold text-ink">{money(account.credit_limit)}</p>
          </div>
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-mint text-ink shadow-mint">
            <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" aria-hidden="true">
              <path d="M4.5 10.5l3.5 3.5 7.5-8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </div>
      </Card>

      <Card className="space-y-5 p-5 sm:p-6">
        <div>
          <p className="text-base font-semibold text-ink">What will you use this credit for?</p>
          <p className="mt-0.5 text-sm text-slate">
            Choose the one that fits best. It cannot be changed later.
          </p>
        </div>

        <PurposeSelect
          options={purposes}
          value={draft.purpose}
          onChange={(value) => {
            // A note typed under Other is dropped when the choice changes, so
            // it cannot be submitted against a purpose it was not written for.
            const option = purposes.find((p) => p.value === value);
            update({ purpose: value, note: option?.requires_note ? draft.note : '' });
            setSubmitError('');
          }}
          error={purposeError}
        />

        {needsNote && (
          <div className="animate-slide-down">
            <Input
              label="Your purpose"
              placeholder="e.g. Home repairs after the monsoon"
              value={draft.note}
              onChange={(event) => update({ note: event.target.value })}
              maxLength={200}
              error={noteError}
              hint={noteError ? undefined : `${note.length}/200`}
              autoFocus
            />
          </div>
        )}

        {submitError && (
          <p className="rounded-xl bg-red-50 px-3.5 py-3 text-sm text-alert" role="alert">{submitError}</p>
        )}

        <Button variant="mint" size="lg" full loading={busy} onClick={submit}>
          Continue
        </Button>
      </Card>
    </div>
  );
}
