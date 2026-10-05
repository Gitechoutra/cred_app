import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import ScoreMeter from '../../components/credit/ScoreMeter';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Loader3D, Row, Skeleton, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { date, money } from '../../utils/format';

/**
 * Check CIBIL Score -> consent -> retrieve -> result.
 *
 * Every bureau pull goes through POST /credit/score/check with the user's
 * consent; this screen never shows a score the backend did not return. While
 * no bureau is connected the backend's sandbox answers, and its results come
 * back flagged is_demo - shown here as demo data, never as a real report.
 */
export default function CreditScore() {
  const toast = useToast();

  // loading | consent | fetching | result | error
  const [step, setStep] = useState('loading');
  const [data, setData] = useState(null);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    endpoints.creditScore
      .get()
      .then((response) => {
        if (cancelled) return;
        setData(response.data);
        setStep(response.data.score ? 'result' : 'consent');
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
        setStep('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function retrieve() {
    if (!agreed) return;
    setStep('fetching');
    try {
      const response = await endpoints.creditScore.check();
      setData(response.data);
      setAgreed(false);
      setStep('result');
    } catch (err) {
      toast.error(err.message);
      setStep('consent');
    }
  }

  const score = data?.score;

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Credit score"
          subtitle="Your CIBIL score and what shapes it"
          back="/home"
        />

        <div className="space-y-4 px-4 pt-1">
          {step === 'loading' && (
            <>
              <Skeleton className="h-56 w-full rounded-3xl" />
              <Skeleton className="h-40 w-full rounded-3xl" />
            </>
          )}

          {step === 'error' && (
            <Card className="text-center">
              <p className="font-semibold text-ink">Could not load your credit score</p>
              <p className="mt-1 text-sm text-slate">{error}</p>
            </Card>
          )}

          {step === 'consent' && (
            <Consent
              canCheck={data?.can_check}
              agreed={agreed}
              setAgreed={setAgreed}
              onRetrieve={retrieve}
              previous={score}
            />
          )}

          {step === 'fetching' && (
            <Card className="flex flex-col items-center py-12 text-center">
              <Loader3D />
              <p className="mt-5 font-semibold text-ink">Retrieving your score</p>
              <p className="mt-1 text-sm text-slate">Contacting the credit bureau…</p>
            </Card>
          )}

          {step === 'result' && score && (
            <Result score={score} onCheckAgain={() => setStep('consent')} />
          )}
        </div>
      </div>
    </div>
  );
}

function DemoNotice() {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5">
      <p className="text-xs leading-relaxed text-amber-900">
        <span className="font-bold">Demo data.</span> CashU is not connected to a
        credit bureau yet, so this score and report are simulated for testing.
        They are not your real CIBIL report.
      </p>
    </div>
  );
}

function Consent({ canCheck, agreed, setAgreed, onRetrieve, previous }) {
  const navigate = useNavigate();

  if (!canCheck) {
    return (
      <Card className="text-center">
        <p className="font-semibold text-ink">Complete KYC first</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-slate">
          Your credit score is looked up with your PAN, which we collect during KYC.
        </p>
        <Button variant="mint" className="mt-4" onClick={() => navigate('/kyc')}>
          Complete KYC
        </Button>
      </Card>
    );
  }

  return (
    <Card className="space-y-4">
      <div>
        <p className="text-base font-bold text-ink">Check your CIBIL score</p>
        <p className="mt-1 text-sm text-slate">
          {previous
            ? `Last checked ${date(previous.fetched_at)}. Get an up-to-date score and report.`
            : 'See your score, credit accounts, utilisation, payment history and recent enquiries.'}
        </p>
      </div>

      <label
        className={cx(
          'flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition-colors',
          agreed ? 'border-mint bg-mint-50/60' : 'border-line',
        )}
      >
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 shrink-0 accent-[#00F5B8]"
          checked={agreed}
          onChange={(event) => setAgreed(event.target.checked)}
        />
        <span className="text-xs leading-relaxed text-slate">
          <span className="block text-sm font-medium text-ink">I give my consent</span>
          I authorise CashU to fetch my credit report from a credit bureau
          (CIBIL, Experian, Equifax or CRIF) using my PAN. This is a soft
          enquiry and does not affect my score.
        </span>
      </label>

      <Button variant="mint" size="lg" full disabled={!agreed} onClick={onRetrieve}>
        Retrieve score
      </Button>
    </Card>
  );
}

function Result({ score, onCheckAgain }) {
  const report = score.report;

  return (
    <>
      {score.is_demo && <DemoNotice />}

      <Card className="text-center">
        <ScoreMeter score={score.score} band={score.no_history ? 'New to credit' : score.band} />
        {score.no_history && (
          <div className="mt-2 space-y-0.5">
            <p className="text-sm font-semibold text-ink">Credit Score: Not Available</p>
            <p className="text-xs text-slate">Status: {score.status_label}</p>
          </div>
        )}
        {score.is_demo && (
          <div className="mt-2 flex justify-center">
            <Badge tone="warn">Demo</Badge>
          </div>
        )}
        <p className="mt-3 text-xs text-slate">
          Last updated {date(score.fetched_at)}
          {score.source === 'APPLICATION' && ' · from your credit application'}
        </p>
        <Button variant="outline" size="sm" className="mt-4" onClick={onCheckAgain}>
          {report ? 'Check again' : 'Get full report'}
        </Button>
      </Card>

      {report ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <Card>
              <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                Credit utilisation
              </p>
              <p className="money mt-2 text-2xl font-bold text-ink">
                {report.utilization.percent != null ? `${report.utilization.percent}%` : '—'}
              </p>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-mist">
                <div
                  className={cx('h-full rounded-full',
                    report.utilization.percent > 30 ? 'bg-warn' : 'bg-mint-600')}
                  style={{ width: `${Math.min(100, report.utilization.percent || 0)}%` }}
                />
              </div>
              <p className="mt-2 text-2xs text-slate">
                {money(report.utilization.total_balance, { decimals: 0 })} used of{' '}
                {money(report.utilization.total_limit, { decimals: 0 })} · keep it under 30%
              </p>
            </Card>

            <Card>
              <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                Payment history
              </p>
              <p className="money mt-2 text-2xl font-bold text-ink">
                {report.payment_history.on_time_percent != null
                  ? `${report.payment_history.on_time_percent}%`
                  : '—'}
              </p>
              <p className="mt-2 text-2xs text-slate">
                On time over {report.payment_history.months_reviewed} months ·{' '}
                {report.payment_history.late_payments} late payment
                {report.payment_history.late_payments === 1 ? '' : 's'}
              </p>
            </Card>
          </div>

          <Card className="py-1">
            <p className="pb-1 pt-3 text-2xs font-semibold uppercase tracking-wider text-slate">
              Credit accounts ({report.accounts.length})
            </p>
            {report.accounts.length === 0 ? (
              <p className="py-3 text-sm text-slate">No credit accounts on file.</p>
            ) : (
              <div className="divide-y divide-line">
                {report.accounts.map((account) => (
                  <div key={`${account.lender}-${account.type}`} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{account.type}</p>
                      <p className="text-2xs text-slate">
                        {account.lender} · opened {date(account.opened_on)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="money text-sm font-semibold text-ink">
                        {money(account.balance, { decimals: 0 })}
                      </p>
                      <p className="text-2xs text-slate">
                        of {money(account.limit, { decimals: 0 })} · {account.status}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="py-1">
            <p className="pb-1 pt-3 text-2xs font-semibold uppercase tracking-wider text-slate">
              Recent enquiries ({report.enquiries.length})
            </p>
            {report.enquiries.length === 0 ? (
              <p className="py-3 text-sm text-slate">No recent enquiries.</p>
            ) : (
              <div className="divide-y divide-line">
                {report.enquiries.map((enquiry) => (
                  <Row
                    key={`${enquiry.date}-${enquiry.lender}`}
                    label={`${enquiry.lender} · ${enquiry.purpose}`}
                    value={date(enquiry.date)}
                  />
                ))}
              </div>
            )}
          </Card>
        </>
      ) : (
        <Card className="text-center">
          <p className="text-sm text-slate">
            This score came from your credit application, which does not include
            the full report. Get the full report to see your accounts,
            utilisation, payment history and enquiries.
          </p>
        </Card>
      )}
    </>
  );
}
