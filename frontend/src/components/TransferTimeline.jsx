import { formatDateTime } from '../utils/money';

/**
 * The state machine, rendered as something a person can follow.
 *
 * A raw status string means nothing to someone whose money is in flight. The
 * backend already shapes this list in transfers/routes.py `_timeline`, so the
 * ordering and the failure relabelling live server-side and this only paints it.
 */
export default function TransferTimeline({ steps = [] }) {
  if (!steps.length) return null;

  return (
    <ol className="space-y-4">
      {steps.map((step, index) => {
        const isLast = index === steps.length - 1;
        return (
          <li key={step.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <Marker done={step.done} failed={step.failed} />
              {!isLast && (
                <span
                  className={`mt-1 w-px flex-1 ${step.done ? 'bg-mint' : 'bg-line'}`}
                  aria-hidden="true"
                />
              )}
            </div>

            <div className="pb-4">
              <p
                className={`text-sm font-medium ${
                  step.failed ? 'text-alert' : step.done ? 'text-ink' : 'text-slate'
                }`}
              >
                {step.label}
              </p>
              {step.at && (
                <p className="mt-0.5 text-xs text-slate tabular">
                  {formatDateTime(step.at)}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Marker({ done, failed }) {
  if (failed) {
    return (
      <span className="grid h-5 w-5 place-items-center rounded-full bg-canvas ring-1 ring-alert">
        <span className="h-2 w-2 rounded-full bg-alert" />
      </span>
    );
  }
  if (done) {
    return (
      <span className="grid h-5 w-5 place-items-center rounded-full bg-mint">
        <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
          <path
            d="M2.5 6.2 4.8 8.5 9.5 3.8"
            fill="none"
            stroke="#0A0F0D"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  return <span className="h-5 w-5 rounded-full border-2 border-line bg-canvas" />;
}
