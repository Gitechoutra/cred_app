import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

/**
 * Purpose of credit. Mandatory, and a real gate rather than a form field.
 *
 * The options come from the server, including which one requires a note, so the
 * list cannot drift from what the backend will accept. The Continue button stays
 * disabled until the choice is actually valid - an enabled button that produces
 * a validation error is a worse experience than one that explains why it is
 * waiting.
 *
 * Choosing here is a one-off: the server refuses a second declaration, so the
 * copy says as much before anyone commits rather than after.
 */

const ICONS = {
  EDUCATION: 'M3 7l9-4 9 4-9 4-9-4zm0 5l9 4 9-4M3 16l9 4 9-4',
  MEDICAL: 'M12 6v12M6 12h12',
  SHOPPING: 'M6 7h12l-1 12H7L6 7zm3 0a3 3 0 016 0',
  TRAVEL: 'M2 13l20-7-7 20-3-8-8-3z',
  BUSINESS: 'M4 8h16v12H4V8zm5 0V5h6v3',
  BILLS: 'M6 3h12v18l-3-2-3 2-3-2-3 2V3zm3 5h6m-6 4h6',
  EMERGENCY: 'M12 3l9 17H3l9-17zm0 6v5m0 3v.5',
  OTHER: 'M6 12h.5m5.5 0h.5m5.5 0h.5',
};

export default function CreditPurpose() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: options, loading } = useFetch(
    () => endpoints.credit.purposes(), [],
  );
  const { data: account } = useFetch(() => endpoints.credit.account(), []);

  const [chosen, setChosen] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const purposes = options?.purposes || [];
  const selected = purposes.find((p) => p.value === chosen);
  const needsNote = Boolean(selected?.requires_note);
  const noteOk = !needsNote || note.trim().length >= 3;
  const ready = Boolean(chosen) && noteOk;

  async function submit() {
    if (!ready || busy) return;
    setBusy(true);
    try {
      await endpoints.credit.setPurpose({
        purpose: chosen,
        // Only sent for the option that asks for it. The server refuses a note
        // on any other purpose, so sending one always would be a bug.
        purpose_note: needsNote ? note.trim() : undefined,
      });
      navigate('/credit/activate', { replace: true });
    } catch (error) {
      toast.error(error?.message || 'We could not save that.');
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <PageHeader title="What is this credit for?" back />
        <Card><Skeleton className="h-72 w-full" /></Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-up">
      <PageHeader
        title="What is this credit for?"
        subtitle="Required before your card can be activated."
        back
      />

      {account?.credit_limit > 0 && (
        <Card className="mb-4 bg-gradient-to-br from-mint-50 to-canvas">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-slate">Your approved limit</span>
            <span className="money text-2xl font-bold text-ink">
              {money(account.credit_limit)}
            </span>
          </div>
        </Card>
      )}

      <Card>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {purposes.map((option, index) => {
            const active = chosen === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  setChosen(option.value);
                  // Clear a note typed under a previous choice, so it cannot be
                  // submitted against a purpose it was not written for.
                  if (!option.requires_note) setNote('');
                }}
                aria-pressed={active}
                style={{ animationDelay: `${index * 30}ms` }}
                className={cx(
                  'stagger flex items-center gap-3 rounded-xl border p-3.5 text-left',
                  'transition-all duration-base ease-glide active:scale-[0.98]',
                  active
                    ? 'border-mint bg-mint-50 shadow-mint'
                    : 'border-line bg-canvas hover:border-ink/20 hover:bg-mist/40',
                )}
              >
                <span
                  className={cx(
                    'grid h-10 w-10 shrink-0 place-items-center rounded-lg',
                    active ? 'bg-mint text-ink' : 'bg-mist text-slate',
                  )}
                >
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
                    <path
                      d={ICONS[option.value] || ICONS.OTHER}
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">
                    {option.label}
                  </span>
                  {option.requires_note && (
                    <span className="mt-0.5 block text-2xs text-slate">
                      Tell us more
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>

        {needsNote && (
          <div className="mt-5 animate-slide-down">
            <Input
              label="What will you use it for?"
              placeholder="Home repairs after the monsoon"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={200}
              hint={`${note.trim().length}/200 - at least a few words.`}
              autoFocus
            />
          </div>
        )}

        <Button
          variant="mint"
          size="lg"
          full
          className="mt-6"
          disabled={!ready}
          loading={busy}
          onClick={submit}
        >
          Continue
        </Button>

        <p className="mt-3 text-center text-2xs leading-relaxed text-slate">
          {chosen
            ? 'You cannot change this later, so pick the one that fits best.'
            : 'Choose one to continue.'}
        </p>
      </Card>
    </div>
  );
}
