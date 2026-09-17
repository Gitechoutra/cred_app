import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, Spinner, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Register an EMI obligation (PRD FR-007).
 *
 * Three steps: pick the lender, enter the loan account number, then confirm
 * what came back. Where the lender is not reachable the same screen falls back
 * to manual entry rather than dead-ending - PRD FR-007 requires that path, and
 * a manually entered loan is verified by an admin before auto-pay is possible.
 */
export default function AddEmi() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data: providers, loading: providersLoading } = useFetch(
    () => endpoints.emi.providers(),
    [],
  );

  const [step, setStep] = useState('provider');
  const [provider, setProvider] = useState(null);
  const [lan, setLan] = useState('');
  const [lanError, setLanError] = useState('');
  const [lookup, setLookup] = useState(null);
  const [manual, setManual] = useState({ emi_amount: '', due_day_of_month: '', total_tenure: '' });
  const [busy, setBusy] = useState(false);

  async function runLookup() {
    if (!lan.trim() || busy) return;

    setBusy(true);
    setLanError('');
    try {
      const response = await endpoints.emi.lookup({
        provider_id: provider.provider_id,
        loan_account_no: lan.trim(),
      });

      if (response?.data?.found) {
        setLookup(response.data);
        setStep('confirm');
      } else {
        const errorMsg =
          response?.data?.reason ||
          response?.message ||
          'Loan account not found. Please enter a valid loan account number.';
        setLanError(errorMsg);
        toast.error(errorMsg);
      }
    } catch (err) {
      const errorMsg =
        err?.message || 'Loan account not found. Please enter a valid loan account number.';
      setLanError(errorMsg);
      toast.error(errorMsg);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);

    try {
      const payload = {
        provider_id: provider.provider_id,
        loan_account_no: lan.trim(),
      };

      if (step === 'manual') {
        payload.emi_amount = Number(manual.emi_amount);
        payload.due_day_of_month = Number(manual.due_day_of_month);
        if (manual.total_tenure) payload.total_tenure = Number(manual.total_tenure);
      }

      const response = await endpoints.emi.add(payload);
      toast.success(response.message);
      navigate(`/emi/${response.data.emi_id}`, { replace: true });
    } catch (err) {
      toast.error(err.message);
      setBusy(false);
    }
  }

  /* ── Step 1: lender ──────────────────────────────────────────────── */
  if (step === 'provider') {
    return (
      <div className="">
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader title="Add an EMI" subtitle="Choose your lender" back="/emi" />

          <div className="px-4 pt-4">
            {providersLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-2xl" />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {(providers || []).map((option) => (
                  <button
                    key={option.provider_id}
                    type="button"
                    onClick={() => {
                      setProvider(option);
                      setStep('account');
                    }}
                    className="flex w-full items-center gap-3 rounded-2xl border border-line bg-canvas p-3.5 text-left transition hover:shadow-card active:scale-[0.99]"
                  >
                    <span
                      className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-xs font-bold text-white"
                      style={{ backgroundColor: option.brand_color || '#0A0F0D' }}
                    >
                      {option.display_name.slice(0, 2).toUpperCase()}
                    </span>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-ink">
                        {option.display_name}
                      </p>
                      <p className="text-2xs text-slate">
                        {option.supports_auto_fetch
                          ? 'Fetches your loan details automatically'
                          : 'Enter your loan details manually'}
                      </p>
                    </div>

                    {option.supports_auto_pay && (
                      <span className="shrink-0 rounded-full bg-mint-50 px-2 py-0.5 text-2xs font-semibold text-mint-800">
                        Auto-pay
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  /* ── Step 2: loan account number ─────────────────────────────────── */
  if (step === 'account') {
    return (
      <div className="">
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader
            title={provider.display_name}
            subtitle="Enter your loan account number"
            back={() => {
              setLanError('');
              setStep('provider');
            }}
          />

          <div className="space-y-4 px-4 pt-4">
            <Input
              label="Loan Account Number (LAN)"
              hint={lanError ? undefined : "Printed on your loan sanction letter or the lender's app."}
              error={lanError}
              autoFocus
              placeholder="LAN4567890"
              value={lan}
              onChange={(event) => {
                setLan(event.target.value.toUpperCase());
                if (lanError) setLanError('');
              }}
            />

            <Button
              variant="mint"
              size="lg"
              full
              disabled={lan.trim().length < 4}
              loading={busy}
              onClick={runLookup}
            >
              {busy ? 'Fetching your loan…' : 'Continue'}
            </Button>

            <div className="flex items-center justify-between px-1">
              <p className="text-xs leading-relaxed text-slate">
                We fetch verified loan details directly from {provider.display_name}.
              </p>
              <button
                type="button"
                onClick={() => {
                  setLanError('');
                  setStep('manual');
                }}
                className="shrink-0 text-xs font-semibold text-mint-700 hover:underline"
              >
                Enter manually
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── Step 3a: confirm what the lender returned ───────────────────── */
  if (step === 'confirm') {
    return (
      <div className="">
        <div className="mx-auto w-full max-w-3xl">
          <PageHeader
            title="Confirm your loan"
            subtitle={provider.display_name}
            back={() => setStep('account')}
          />

          <div className="space-y-4 px-4 pt-4">
            <div className="rounded-2xl border border-mint-200 bg-mint-50 p-4">
              <p className="text-xs font-semibold text-mint-800">
                Loan found with {provider.display_name}
              </p>
              <p className="money mt-2 text-3xl font-bold text-ink">
                {money(lookup.emi_amount)}
                <span className="ml-1 text-sm font-medium text-slate">/ month</span>
              </p>
            </div>

            <Card className="divide-y divide-line py-1">
              <Row label="Loan account" value={lookup.loan_account_masked} mono />
              <Row label="Next due" value={date(lookup.next_due_date)} />
              <Row label="Due day" value={`${lookup.due_day_of_month} of every month`} />
              <Row
                label="Tenure remaining"
                value={`${lookup.tenure_remaining} of ${lookup.total_tenure}`}
                mono
              />
              <Row label="Outstanding" value={money(lookup.outstanding_bal)} mono />
              {lookup.interest_rate ? (
                <Row label="Interest rate" value={`${lookup.interest_rate}%`} mono />
              ) : null}
            </Card>

            <Button variant="mint" size="lg" full loading={busy} onClick={save}>
              Add this EMI
            </Button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Step 3b: manual entry ───────────────────────────────────────── */
  const manualValid = manual.emi_amount && manual.due_day_of_month;

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Enter loan details"
          subtitle={provider.display_name}
          back={() => setStep('account')}
        />

        <div className="space-y-4 px-4 pt-4">
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5">
            <p className="text-xs leading-relaxed text-amber-900">
              {lookup?.reason
                || 'We could not reach your lender. Enter your details and we will verify them against your loan document.'}
            </p>
          </div>

          <Input
            label="Monthly EMI amount"
            prefix="₹"
            inputMode="numeric"
            autoFocus
            placeholder="4250"
            value={manual.emi_amount}
            onChange={(event) =>
              setManual({ ...manual, emi_amount: event.target.value.replace(/\D/g, '') })
            }
          />

          <Input
            label="Due day of month"
            hint="For example, 5 if your EMI is due on the 5th."
            inputMode="numeric"
            maxLength={2}
            placeholder="5"
            value={manual.due_day_of_month}
            onChange={(event) =>
              setManual({ ...manual, due_day_of_month: event.target.value.replace(/\D/g, '') })
            }
          />

          <Input
            label="Total tenure"
            hint="Number of installments. Optional."
            inputMode="numeric"
            placeholder="12"
            value={manual.total_tenure}
            onChange={(event) =>
              setManual({ ...manual, total_tenure: event.target.value.replace(/\D/g, '') })
            }
          />

          <Button variant="mint" size="lg" full disabled={!manualValid} loading={busy} onClick={save}>
            Add this EMI
          </Button>

          <p className="px-1 text-xs leading-relaxed text-slate">
            Auto-pay becomes available once our team verifies these details
            against your loan sanction letter. You can upload it from the EMI
            screen after adding.
          </p>
        </div>
      </div>
    </div>
  );
}
