import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import ScoreMeter, { bureauLabel } from '../../components/credit/ScoreMeter';
import { PageHeader } from '../../components/layout/AppShell';
import { Badge, Button, Card, Loader3D, Row, Skeleton, cx } from '../../components/ui';
import { date, money } from '../../utils/format';

/**
 * Check credit score -> consent -> retrieve -> result.
 *
 * Every bureau pull goes through POST /credit/score/check with the user's
 * consent; this screen never shows a score the backend did not return, and
 * always names the bureau it came from. Anything that is not a real report -
 * the sandbox, or a provider's test environment - comes back is_demo and is
 * labelled as test data.
 */
export default function CreditScore() {
  // loading | load-error | consent | fetching | result
  const [step, setStep] = useState('loading');
  const [data, setData] = useState(null);
  const [agreed, setAgreed] = useState(false);
  const [loadError, setLoadError] = useState('');
  // The last failed check, shown on the consent card: { message, retryable }.
  const [checkError, setCheckError] = useState(null);

  const load = useCallback(() => {
    let cancelled = false;
    setStep('loading');
    endpoints.creditScore
      .get()
      .then((response) => {
        if (cancelled) return;
        setData(response.data);
        setStep(response.data.score ? 'result' : 'consent');
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err.message);
        setStep('load-error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  async function retrieve() {
    if (!agreed) return;
    setCheckError(null);
    setStep('fetching');
    try {
      const response = await endpoints.creditScore.check();
      setData(response.data);
      setAgreed(false);
      setStep('result');
    } catch (err) {
      // A bureau outage is worth retrying; a refused request, a missing PAN or
      // the daily limit is not, until something changes.
      setCheckError({
        message: err.message,
        retryable: err.status >= 500 || !err.status,
      });
      setStep('consent');
    }
  }

  const score = data?.score;

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Credit score"
          subtitle="Your credit score and what shapes it"
          back="/home"
        />

        <div className="space-y-4 px-4 pt-1">
          {step === 'loading' && (
            <>
              <Skeleton className="h-56 w-full rounded-3xl" />
              <Skeleton className="h-40 w-full rounded-3xl" />
            </>
          )}

          {step === 'load-error' && (
            <Card className="text-center">
              <p className="font-semibold text-ink">Could not load your credit score</p>
              <p className="mt-1 text-sm text-slate">{loadError}</p>
              <Button variant="outline" size="sm" className="mt-4" onClick={load}>
                Try again
              </Button>
            </Card>
          )}

          {step === 'consent' && (
            <Consent
              canCheck={data?.can_check}
              bureau={data?.bureau}
              agreed={agreed}
              setAgreed={setAgreed}
              onRetrieve={retrieve}
              error={checkError}
              previous={score}
              onBack={score ? () => { setCheckError(null); setStep('result'); } : null}
            />
          )}

          {step === 'fetching' && (
            <Card className="flex flex-col items-center py-12 text-center">
              <Loader3D />
              <p className="mt-5 font-semibold text-ink">Retrieving your score</p>
              <p className="mt-1 text-sm text-slate">
                Contacting {bureauLabel(data?.bureau?.bureau)}…
              </p>
            </Card>
          )}

          {step === 'result' && score && (
            <Result
              score={score}
              canCheck={data?.bureau?.available}
              onCheckAgain={() => setStep('consent')}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** Says plainly when a score is not a real person's real report. */
function TestDataNotice({ score }) {
  const sandbox = score.provider === 'SANDBOX' || score.bureau === 'SANDBOX';
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5">
      <p className="text-xs leading-relaxed text-amber-900">
        {sandbox ? (
          <>
            <span className="font-bold">Sandbox data.</span> No credit bureau was
            contacted. This score and report are simulated for testing and are
            not your real credit report.
          </>
        ) : (
          <>
            <span className="font-bold">Test data.</span> This came from{' '}
            {bureauLabel(score.bureau)}&apos;s test environment, which answers
            with sample files. It is not your real credit report.
          </>
        )}
      </p>
    </div>
  );
}

function Consent({ canCheck, bureau, agreed, setAgreed, onRetrieve, error, previous, onBack }) {
  const navigate = useNavigate();

  if (bureau && !bureau.available) {
    return (
      <Card className="text-center">
        <p className="font-semibold text-ink">Credit score checks are not available yet</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-slate">
          We are not connected to a credit bureau right now. Please check back later.
        </p>
        {onBack && (
          <Button variant="outline" size="sm" className="mt-4" onClick={onBack}>
            Back to my last score
          </Button>
        )}
      </Card>
    );
  }

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

  const sandbox = bureau?.provider === 'SANDBOX';
  const source = sandbox
    ? 'the CashU test sandbox (no real credit bureau is contacted)'
    : bureauLabel(bureau?.bureau);

  return (
    <Card className="space-y-4">
      <div>
        <p className="text-base font-bold text-ink">Check your credit score</p>
        <p className="mt-1 text-sm text-slate">
          {previous
            ? `Last checked ${date(previous.fetched_at)}. Get an up-to-date score and report.`
            : 'See your score, credit accounts, utilisation, payment history and recent enquiries.'}
        </p>
      </div>

      {bureau?.is_test && (
        <Badge tone="warn">{sandbox ? 'Sandbox' : 'Test environment'}</Badge>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3.5" role="alert">
          <p className="text-sm font-medium text-red-800">{error.message}</p>
          {error.retryable && (
            <p className="mt-0.5 text-xs text-red-700">
              No score was recorded. You can try again.
            </p>
          )}
        </div>
      )}

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
          I authorise CashU to fetch my credit report from {source} using my
          PAN, name and mobile number. This is a soft enquiry and does not
          affect my score.
        </span>
      </label>

      <Button variant="mint" size="lg" full disabled={!agreed} onClick={onRetrieve}>
        {error?.retryable ? 'Try again' : 'Retrieve score'}
      </Button>

      {onBack && (
        <Button variant="ghost" size="sm" full onClick={onBack}>
          Back to my last score
        </Button>
      )}
    </Card>
  );
}

function Result({ score, canCheck, onCheckAgain }) {
  const report = score.report;

  return (
    <>
      {score.is_demo && <TestDataNotice score={score} />}

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
            <Badge tone="warn">Test data</Badge>
          </div>
        )}
        <p className="mt-3 text-xs text-slate">
          {score.bureau && score.bureau !== 'SANDBOX' && <>From {bureauLabel(score.bureau)} · </>}
          Last updated {date(score.fetched_at)}
          {score.source === 'APPLICATION' && ' · from your credit application'}
        </p>
        {canCheck && (
          <Button variant="outline" size="sm" className="mt-4" onClick={onCheckAgain}>
            {report ? 'Check again' : 'Get full report'}
          </Button>
        )}
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
                {report.payment_history.months_reviewed ? (
                  <>
                    On time over {report.payment_history.months_reviewed} months ·{' '}
                    {report.payment_history.late_payments} late payment
                    {report.payment_history.late_payments === 1 ? '' : 's'}
                  </>
                ) : 'No repayment history reported yet'}
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
                {report.accounts.map((account, index) => (
                  <div key={`${index}-${account.lender}`} className="flex items-center justify-between gap-3 py-3">
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
                        {account.limit != null && <>of {money(account.limit, { decimals: 0 })} · </>}
                        {account.status}
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
                {report.enquiries.map((enquiry, index) => (
                  <Row
                    key={`${index}-${enquiry.date}`}
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
