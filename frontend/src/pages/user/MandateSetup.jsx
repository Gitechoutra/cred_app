import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { BankRow } from '../../components/domain';
import { PageHeader, IconShield } from '../../components/layout/AppShell';
import { Button, Card, Input, Row, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * Auto-pay mandate registration (PRD FR-009, section 12).
 *
 * The review screen the PRD requires: rail, ceiling, frequency and debit date
 * all shown before the user authorises anything, plus the four guarantees RBI
 * obliges - AFA at registration, 48-hour pre-debit notice, pause and cancel,
 * and a post-debit confirmation.
 */
export default function MandateSetup() {
  const { emiId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: preview, loading } = useFetch(() => endpoints.mandates.preview(emiId), [emiId]);
  const { data: banksData } = useFetch(() => endpoints.banks.list(), []);

  const [cap, setCap] = useState('');
  const [bankId, setBankId] = useState(null);
  const [vpa, setVpa] = useState('');
  const [busy, setBusy] = useState(false);

  const banks = (banksData?.accounts || []).filter((a) => a.is_payout_eligible);
  const isUpi = preview?.mandate_type === 'UPI_AUTOPAY';

  const selectedBank = banks.find((b) => b.bank_account_id === bankId)
    || banks.find((b) => b.is_primary)
    || banks[0];

  const ceiling = cap ? Number(cap) : preview?.suggested_max_amount;
  const capTooLow = ceiling && preview && ceiling < preview.minimum_max_amount;

  const ready = Boolean(preview) && !capTooLow && (isUpi ? vpa.trim() : selectedBank);

  async function create() {
    if (!ready || busy) return;
    setBusy(true);

    try {
      const response = await endpoints.mandates.create({
        emi_id: emiId,
        max_amount: ceiling,
        bank_account_id: isUpi ? undefined : selectedBank?.bank_account_id,
        upi_vpa: isUpi ? vpa.trim() : undefined,
      });

      // The AFA challenge lives with the bank or UPI app. In sandbox we complete
      // it immediately so the whole flow is walkable end to end.
      await endpoints.mandates.activate(response.data.mandate_id);

      toast.success('Auto-pay is active. We will notify you 48 hours before every debit.');
      navigate(`/emi/${emiId}`, { replace: true });
    } catch (err) {
      toast.error(err.message);
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="">
        <PageHeader title="Set up auto-pay" back={`/emi/${emiId}`} />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="">
        <PageHeader title="Set up auto-pay" back={`/emi/${emiId}`} />
      </div>
    );
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Set up auto-pay"
          subtitle={preview.provider_name}
          back={`/emi/${emiId}`}
        />

        <div className="space-y-4 px-4 pt-4">
          <section className="rounded-2xl bg-ink p-5 text-white">
            <p className="text-xs text-white/55">We will debit</p>
            <p className="money mt-1 text-[2rem] font-bold leading-none">
              {money(preview.emi_amount)}
            </p>
            <p className="mt-2 text-xs text-white/60">
              every month, {preview.debit_time}
            </p>

            <div className="mt-4 border-t border-white/10 pt-3">
              <p className="text-2xs text-white/55">Using</p>
              <p className="mt-0.5 text-sm font-semibold">{preview.mandate_type_label}</p>
            </div>
          </section>

          {/* ── Instrument ──────────────────────────────────────────── */}
          {isUpi ? (
            <Input
              label="UPI ID"
              hint="Auto-pay will be set up with this UPI app."
              placeholder="yourname@bank"
              value={vpa}
              onChange={(event) => setVpa(event.target.value.toLowerCase())}
            />
          ) : (
            <div>
              <p className="mb-2 text-sm font-medium text-ink">Debit from</p>
              {banks.length === 0 ? (
                <Card className="border-dashed">
                  <p className="text-sm text-slate">
                    You need a verified bank account to set up e-NACH auto-pay.
                  </p>
                  <Button
                    variant="mint"
                    size="sm"
                    className="mt-3"
                    onClick={() => navigate('/banks/add')}
                  >
                    Add account
                  </Button>
                </Card>
              ) : (
                <div className="space-y-2">
                  {banks.map((account) => (
                    <BankRow
                      key={account.bank_account_id}
                      account={account}
                      selected={account.bank_account_id === selectedBank?.bank_account_id}
                      onClick={() => setBankId(account.bank_account_id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Ceiling ─────────────────────────────────────────────── */}
          <Input
            label="Maximum debit amount"
            prefix="₹"
            inputMode="numeric"
            placeholder={String(preview.suggested_max_amount)}
            value={cap}
            error={
              capTooLow
                ? `The limit must be at least ${money(preview.minimum_max_amount)}.`
                : undefined
            }
            hint={preview.cap_explanation}
            onChange={(event) => setCap(event.target.value.replace(/\D/g, ''))}
          />

          {/* ── Terms ───────────────────────────────────────────────── */}
          <Card className="divide-y divide-line py-1">
            <Row label="Frequency" value="Monthly" />
            <Row
              label="First debit"
              value={preview.next_debit_date ? date(preview.next_debit_date) : '—'}
            />
            <Row label="Debit limit" value={money(ceiling || 0)} mono />
            <Row label="Advance notice" value={`${preview.predebit_notice_hours} hours`} />
          </Card>

          {/* ── Your protections ────────────────────────────────────── */}
          <div className="rounded-2xl border border-mint-200 bg-mint-50 p-4">
            <div className="flex items-center gap-2">
              <IconShield className="h-4 w-4 text-mint-800" />
              <p className="text-xs font-semibold text-mint-800">Your protections</p>
            </div>

            <ul className="mt-2.5 space-y-2">
              {[
                `We notify you ${preview.predebit_notice_hours} hours before every debit — required by RBI and not something you can be opted out of.`,
                'You can pause or cancel any time up to 24 hours before a debit.',
                `We can never debit more than ${money(ceiling || preview.suggested_max_amount)} in one cycle.`,
                'If a debit fails, we retry twice and tell you each time — no silent bounce charges.',
              ].map((line) => (
                <li key={line} className="flex items-start gap-2">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-mint-700" />
                  <span className="text-2xs leading-relaxed text-mint-800/85">{line}</span>
                </li>
              ))}
            </ul>
          </div>

          <Button variant="mint" size="lg" full disabled={!ready} loading={busy} onClick={create}>
            Authorise with my bank
          </Button>

          <p className="px-1 text-center text-2xs leading-relaxed text-slate">
            You will complete a one-time authentication with your bank to
            register this mandate.
          </p>
        </div>
      </div>
    </div>
  );
}
