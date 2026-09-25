import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useProfile } from '../../hooks/useProfile';
import { StepDots } from './ProfileSetup';
import PinPad, { PinDots } from './PinPad';

/**
 * MPIN creation.
 *
 * Enter, then confirm. The weak-PIN rules are enforced server-side too, but
 * catching them here means the user is told before they have typed it twice.
 */
export default function MpinSetup() {
  const navigate = useNavigate();
  const { refresh } = useProfile();
  const toast = useToast();

  const [stage, setStage] = useState('create');
  const [pin, setPin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const value = stage === 'create' ? pin : confirm;
  const setValue = stage === 'create' ? setPin : setConfirm;

  function weakness(candidate) {
    if (new Set(candidate).size === 1) {
      return 'Avoid repeating the same digit.';
    }
    const ascending = '01234567890';
    const descending = '09876543210';
    if (ascending.includes(candidate) || descending.includes(candidate)) {
      return 'Avoid consecutive digits.';
    }
    return null;
  }

  function press(digit) {
    if (value.length >= 6) return;

    const next = value + digit;
    setValue(next);
    setError('');

    if (next.length !== 6) return;

    if (stage === 'create') {
      const weak = weakness(next);
      if (weak) {
        setError(weak);
        setTimeout(() => setPin(''), 400);
        return;
      }
      setTimeout(() => setStage('confirm'), 180);
      return;
    }

    if (next !== pin) {
      setError('Those PINs do not match. Try again.');
      setTimeout(() => {
        setConfirm('');
        setStage('create');
        setPin('');
      }, 600);
      return;
    }

    submit(next);
  }

  function back() {
    setValue(value.slice(0, -1));
    setError('');
  }

  async function submit(finalPin) {
    setLoading(true);

    try {
      await endpoints.auth.setMpin(finalPin);
      await refresh();
      toast.success('Your MPIN is set.');
      navigate('/home', { replace: true });
    } catch (err) {
      setError(err.message);
      setConfirm('');
      setPin('');
      setStage('create');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-6 py-8">
        <PageHeader title="" back={true} sticky={false} />
        <StepDots current={2} total={2} />

        <div className="flex flex-1 flex-col items-center justify-center py-8">
          <h1 className="text-center text-2xl font-bold tracking-tight text-ink">
            {stage === 'create' ? 'Create your MPIN' : 'Confirm your MPIN'}
          </h1>
          <p className="mt-2 max-w-xs text-center text-sm text-slate">
            {stage === 'create'
              ? 'A 6-digit PIN to unlock CashU and authorise payments.'
              : 'Enter it once more so we know it is right.'}
          </p>

          <PinDots length={6} filled={value.length} error={Boolean(error)} className="mt-10" />

          {error && <p className="mt-4 text-center text-sm text-alert">{error}</p>}
        </div>

        <PinPad onPress={press} onBackspace={back} disabled={loading} />
      </div>
    </div>
  );
}
