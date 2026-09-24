import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { PageHeader, IconCheck, IconShield } from '../../components/layout/AppShell';
import { Badge, Button, Card, Input, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch, useProfile } from '../../hooks/useProfile';
import { money, statusLabel, statusTone } from '../../utils/format';

/**
 * KYC submission (PRD FR-012, section 18).
 *
 * Two tiers, and the screen leads with what each one unlocks rather than what
 * each one demands - a user uploading a PAN card wants to know what they get,
 * not to be told about compliance.
 */
export default function Kyc() {
  const navigate = useNavigate();
  const toast = useToast();
  const { refresh } = useProfile();

  const { data: kyc, loading, refetch } = useFetch(() => endpoints.kyc.status(), []);

  const [tier, setTier] = useState('MINIMUM');
  const [pan, setPan] = useState('');
  const [aadhaar, setAadhaar] = useState('');
  const [name, setName] = useState('');
  const [files, setFiles] = useState({});
  const [busy, setBusy] = useState(false);

  const panRef = useRef();
  const aadhaarRef = useRef();

  const wantsFull = tier === 'FULL';
  const valid =
    /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan) &&
    name.trim().length >= 2 &&
    files.pan &&
    (!wantsFull || (/^\d{12}$/.test(aadhaar) && files.aadhaar));

  async function submit(event) {
    event.preventDefault();
    if (!valid || busy) return;

    setBusy(true);

    try {
      const form = new FormData();
      form.append('pan_number', pan);
      form.append('full_name', name.trim());
      form.append('requested_tier', tier);
      form.append('pan_document', files.pan);
      if (wantsFull) {
        form.append('aadhaar_number', aadhaar);
        form.append('aadhaar_document', files.aadhaar);
      }

      await endpoints.kyc.submit(form);
      await refresh();
      refetch();

      toast.success('KYC submitted. Verification usually completes within 24 hours.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="">
        <PageHeader title="KYC verification" back="/profile" />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  const submitted = ['PENDING', 'UNDER_REVIEW'].includes(kyc?.kyc_status);
  const approved = kyc?.kyc_status === 'APPROVED';

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="KYC verification" back="/profile" />

        <div className="space-y-4 px-4 pt-4">
          {/* ── Current state ───────────────────────────────────────── */}
          <section
            className={cx(
              'rounded-2xl p-5',
              approved ? 'bg-ink text-white' : 'border border-line bg-canvas',
            )}
          >
            <div className="flex items-center justify-between">
              <p className={cx('text-xs', approved ? 'text-white/55' : 'text-slate')}>
                Verification status
              </p>
              <Badge tone={approved ? 'good' : statusTone(kyc.kyc_status)} dot>
                {statusLabel(kyc.kyc_status)}
              </Badge>
            </div>

            <p className={cx('mt-3 text-lg font-bold', approved ? 'text-mint' : 'text-ink')}>
              {approved ? `${kyc.kyc_tier} KYC verified` : 'Not yet verified'}
            </p>

            <p className={cx('mt-1 text-xs', approved ? 'text-white/60' : 'text-slate')}>
              Credit limit up to{' '}
              <span className="money font-medium">
                {money(kyc.capabilities.max_credit_limit)}
              </span>
            </p>

            {kyc.rejection_reason && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-alert">
                {kyc.rejection_reason}
              </p>
            )}
          </section>

          {/* ── Tiers ───────────────────────────────────────────────── */}
          <div className="space-y-2">
            {kyc.tiers.map((option) => (
              <div
                key={option.tier}
                className={cx(
                  'rounded-2xl border p-4',
                  option.active ? 'border-mint bg-mint-50' : 'border-line bg-canvas',
                )}
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-ink">{option.label}</p>
                  {option.active && (
                    <span className="flex items-center gap-1 text-2xs font-semibold text-mint-800">
                      <IconCheck className="h-3 w-3" />
                      Active
                    </span>
                  )}
                </div>

                <p className="money mt-1 text-xs text-slate">
                  Credit limit up to {money(option.max_credit_limit)}
                </p>

                <p className="mt-2 text-2xs text-slate">
                  Requires: {option.requirements.join(', ')}
                </p>
              </div>
            ))}
          </div>

          {/* ── Submission ──────────────────────────────────────────── */}
          {submitted ? (
            <Card className="text-center">
              <p className="text-sm font-medium text-ink">Your documents are under review</p>
              <p className="mt-1 text-xs text-slate">
                We will notify you as soon as verification completes — usually
                within 24 hours.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => navigate('/home')}
              >
                Back to home
              </Button>
            </Card>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              {kyc.capabilities.can_upgrade && (
                <div>
                  <p className="mb-2 text-sm font-medium text-ink">Verify with</p>
                  <div className="grid grid-cols-2 gap-2">
                    {['MINIMUM', 'FULL'].map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => setTier(option)}
                        className={cx(
                          'rounded-xl border p-3 text-left transition',
                          tier === option
                            ? 'border-mint bg-mint-50 ring-2 ring-mint/25'
                            : 'border-line hover:border-ink/20',
                        )}
                      >
                        <p className="text-sm font-semibold text-ink">
                          {option === 'MINIMUM' ? 'PAN only' : 'PAN + Aadhaar'}
                        </p>
                        <p className="money mt-0.5 text-2xs text-slate">
                          {money(
                            kyc.tiers.find((t) => t.tier === option)?.max_credit_limit || 0,
                          )}{' '}
                          limit
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <Input
                label="Full name (as per PAN)"
                placeholder="VIKRAM SHARMA"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />

              <Input
                label="PAN number"
                placeholder="ABCDE1234F"
                value={pan}
                maxLength={10}
                onChange={(event) => setPan(event.target.value.toUpperCase())}
              />

              <FileField
                label="PAN card photo"
                file={files.pan}
                inputRef={panRef}
                onSelect={(file) => setFiles({ ...files, pan: file })}
              />

              {wantsFull && (
                <>
                  <Input
                    label="Aadhaar number"
                    placeholder="1234 5678 9012"
                    inputMode="numeric"
                    value={aadhaar}
                    maxLength={12}
                    onChange={(event) => setAadhaar(event.target.value.replace(/\D/g, ''))}
                  />

                  <FileField
                    label="Aadhaar photo"
                    file={files.aadhaar}
                    inputRef={aadhaarRef}
                    onSelect={(file) => setFiles({ ...files, aadhaar: file })}
                  />
                </>
              )}

              <div className="flex items-start gap-2.5 rounded-xl bg-mist px-3.5 py-3">
                <IconShield className="mt-0.5 h-4 w-4 shrink-0 text-slate" />
                <p className="text-xs leading-relaxed text-slate">
                  Your documents are encrypted at rest and visible only to
                  authorised compliance staff, whose access is logged. We are
                  required to verify your identity before you can move money.
                </p>
              </div>

              <Button type="submit" variant="mint" size="lg" full disabled={!valid} loading={busy}>
                Submit for verification
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function FileField({ label, file, inputRef, onSelect }) {
  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>

      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,application/pdf"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) onSelect(selected);
        }}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className={cx(
          'flex w-full items-center gap-3 rounded-xl border-2 border-dashed p-3.5 text-left transition',
          file ? 'border-mint bg-mint-50' : 'border-line hover:border-ink/20',
        )}
      >
        <span
          className={cx(
            'grid h-9 w-9 shrink-0 place-items-center rounded-lg',
            file ? 'bg-mint text-ink' : 'bg-mist text-slate',
          )}
        >
          {file ? (
            <IconCheck className="h-4 w-4" />
          ) : (
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M12 16V4M7 9l5-5 5 5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 17v3h16v-3" strokeLinecap="round" />
            </svg>
          )}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink">
            {file ? file.name : 'Tap to upload'}
          </p>
          <p className="text-2xs text-slate">
            {file
              ? `${(file.size / 1024).toFixed(0)} KB`
              : 'JPG, PNG or PDF · max 10 MB'}
          </p>
        </div>
      </button>
    </div>
  );
}
