import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Input } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useProfile } from '../../hooks/useProfile';

export default function ProfileSetup() {
  const navigate = useNavigate();
  const { refresh } = useProfile();
  const toast = useToast();

  const [form, setForm] = useState({ full_name: '', email: '', date_of_birth: '' });
  const [accepted, setAccepted] = useState(false);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const canSubmit = form.full_name.trim().length >= 2 && accepted;

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: '' }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit || loading) return;

    setLoading(true);

    try {
      await endpoints.auth.register({
        full_name: form.full_name.trim(),
        email: form.email.trim() || undefined,
        date_of_birth: form.date_of_birth || undefined,
        terms_accepted: true,
      });

      await refresh();
      navigate('/onboarding/mpin', { replace: true });
    } catch (err) {
      if (err.details?.field) {
        setErrors({ [err.details.field]: err.message });
      } else {
        toast.error(err.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto w-full max-w-md px-6 py-8">
        <PageHeader title="" back={true} sticky={false} />
        <StepDots current={1} total={2} />

        <h1 className="mt-6 text-2xl font-bold tracking-tight text-ink">
          Tell us who you are
        </h1>
        <p className="mt-2 text-sm text-slate">
          Enter your name exactly as it appears on your PAN card. We use it to
          verify that your bank accounts belong to you.
        </p>

        <form onSubmit={submit} className="mt-8 space-y-4">
          <Input
            label="Full name (as per PAN)"
            placeholder="Vikram Sharma"
            autoFocus
            autoComplete="name"
            value={form.full_name}
            error={errors.full_name}
            onChange={(event) => update('full_name', event.target.value)}
          />

          <Input
            label="Email"
            hint="For receipts and statements. Optional."
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
            value={form.email}
            error={errors.email}
            onChange={(event) => update('email', event.target.value)}
          />

          <Input
            label="Date of birth"
            hint="Optional."
            type="date"
            max={new Date().toISOString().slice(0, 10)}
            value={form.date_of_birth}
            error={errors.date_of_birth}
            onChange={(event) => update('date_of_birth', event.target.value)}
          />

          <label className="flex cursor-pointer items-start gap-3 pt-2">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(event) => setAccepted(event.target.checked)}
              className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer rounded border-line accent-mint"
            />
            <span className="text-xs leading-relaxed text-slate">
              I agree to the{' '}
              <span className="font-medium text-ink underline">Terms of Service</span>{' '}
              and{' '}
              <span className="font-medium text-ink underline">Privacy Policy</span>,
              and consent to CashU processing my data as described.
            </span>
          </label>

          <Button
            type="submit"
            variant="mint"
            size="lg"
            full
            className="mt-2"
            disabled={!canSubmit}
            loading={loading}
          >
            Continue
          </Button>
        </form>
      </div>
    </div>
  );
}

export function StepDots({ current, total }) {
  return (
    <div className="flex items-center gap-1.5" aria-label={`Step ${current} of ${total}`}>
      {Array.from({ length: total }, (_, index) => (
        <span
          key={index}
          className={[
            'h-1 rounded-full transition-all',
            index < current ? 'w-8 bg-mint' : 'w-4 bg-line',
          ].join(' ')}
        />
      ))}
    </div>
  );
}
