import { useEffect, useRef, useState } from 'react';

import { endpoints } from '../../api/client';
import { Spinner, cx } from '../../components/ui';

/**
 * Renders an uploaded KYC document for review.
 *
 * The file is not served statically — it comes back through an authenticated,
 * audited admin endpoint — so it is fetched as a blob and shown from an object
 * URL. That URL is revoked on unmount; without that, every document a reviewer
 * opens stays in memory for the life of the tab.
 *
 * Uploads accept PDF as well as PNG and JPEG, so this branches on the MIME type
 * the endpoint returns. A PDF rendered into an <img> silently shows nothing,
 * which would leave a reviewer approving a document they never actually saw.
 *
 * Zoom exists because the job here is judging whether a PAN card is genuine,
 * and that decision turns on small details: the hologram, the font of the
 * number, the alignment of the photo. A thumbnail cannot support it.
 */
export default function KycDocumentViewer({ kycId, slot, label, available }) {
  const [url, setUrl] = useState(null);
  const [type, setType] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [zoomed, setZoomed] = useState(false);

  /* Distinct from `error`: the file arrived, the browser just cannot paint it.
     For a reviewer that is itself evidence, so it must not look like a network
     failure and must not take the download link away with it. */
  const [unrenderable, setUnrenderable] = useState(false);

  const objectUrl = useRef(null);

  useEffect(() => {
    if (!available || !kycId) return undefined;

    let cancelled = false;
    setLoading(true);
    setError('');
    setUnrenderable(false);

    (async () => {
      try {
        const next = await endpoints.admin.kycDocumentUrl(kycId, slot);
        if (cancelled) {
          URL.revokeObjectURL(next.url);
          return;
        }
        objectUrl.current = next.url;
        setUrl(next.url);
        setType(next.type || '');
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl.current) {
        URL.revokeObjectURL(objectUrl.current);
        objectUrl.current = null;
      }
    };
  }, [kycId, slot, available]);

  if (!available) {
    return (
      <div className="rounded-xl border border-dashed border-line bg-mist/50 p-5 text-center">
        <p className="text-xs font-medium text-slate">{label} not uploaded</p>
      </div>
    );
  }

  const isPdf = type === 'application/pdf';
  const canEnlarge = Boolean(url) && !unrenderable;

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-line bg-mist">
        <div className="flex items-center justify-between border-b border-line bg-canvas px-3 py-2">
          <p className="text-2xs font-bold uppercase tracking-[0.12em] text-slate">
            {label}
          </p>

          {/* Kept available even when the preview fails — a reviewer who cannot
              see the file in the panel still needs to get at the bytes. */}
          {url && (
            <div className="flex items-center gap-1">
              {canEnlarge && (
                <button
                  type="button"
                  onClick={() => setZoomed(true)}
                  className="rounded-lg px-2 py-1 text-2xs font-semibold text-mint-700 transition hover:bg-mint-50"
                >
                  Enlarge
                </button>
              )}
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg px-2 py-1 text-2xs font-medium text-slate transition hover:bg-mist hover:text-ink"
              >
                Open
              </a>
            </div>
          )}
        </div>

        <div className="grid min-h-[190px] place-items-center p-3">
          {loading && <Spinner className="h-5 w-5 text-slate" />}

          {error && (
            <div className="px-4 text-center">
              <p className="text-xs font-medium text-alert">{error}</p>
            </div>
          )}

          {url && !error && unrenderable && (
            <div className="px-4 text-center">
              <p className="text-xs font-semibold text-warn">
                This file cannot be displayed.
              </p>
              <p className="mx-auto mt-1.5 max-w-xs text-2xs leading-relaxed text-slate">
                The document was uploaded but is not a readable image or PDF —
                it may be truncated or corrupt. Open it to inspect the raw file.
                Do not approve a submission you have not been able to see.
              </p>
            </div>
          )}

          {url && !error && !unrenderable && isPdf && (
            <object
              data={url}
              type="application/pdf"
              aria-label={label}
              className="h-64 w-full rounded-lg"
            >
              <p className="p-4 text-center text-2xs text-slate">
                Your browser cannot preview PDFs inline. Use Open above.
              </p>
            </object>
          )}

          {url && !error && !unrenderable && !isPdf && (
            <button
              type="button"
              onClick={() => setZoomed(true)}
              className="block w-full cursor-zoom-in"
              title="Click to enlarge"
            >
              <img
                src={url}
                alt={label}
                className="mx-auto max-h-64 w-auto rounded-lg object-contain shadow-card"
                onError={() => setUnrenderable(true)}
              />
            </button>
          )}
        </div>
      </div>

      {/* Full-screen inspection. */}
      {zoomed && url && (
        <div
          className="fixed inset-0 z-[80] flex flex-col bg-ink/90 backdrop-blur-sm"
          onClick={() => setZoomed(false)}
        >
          <div className="flex items-center justify-between px-5 py-3">
            <p className="text-sm font-semibold text-white">{label}</p>
            <button
              type="button"
              onClick={() => setZoomed(false)}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-white/70 transition hover:bg-white/10 hover:text-white"
            >
              Close
            </button>
          </div>

          <div className="flex flex-1 items-center justify-center overflow-auto p-5">
            {isPdf ? (
              <object
                data={url}
                type="application/pdf"
                aria-label={label}
                onClick={(event) => event.stopPropagation()}
                className="h-full w-full rounded-lg bg-canvas"
              />
            ) : (
              <img
                src={url}
                alt={label}
                onClick={(event) => event.stopPropagation()}
                className="max-h-full max-w-full cursor-zoom-out rounded-lg object-contain"
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

/**
 * The authenticity gate.
 *
 * The brief requires the reviewer to judge whether the document looks like a
 * genuine PAN card before approving. Making that an explicit, deliberate tick
 * — rather than an assumption baked into the Approve button — means the
 * reviewer has to look, and the approval that follows carries their attested
 * judgement rather than a reflex click.
 */
export function AuthenticityGate({ checked, onChange }) {
  return (
    <label
      className={cx(
        'flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition',
        checked ? 'border-mint bg-mint-50' : 'border-warn/30 bg-amber-50/60',
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer rounded border-line accent-mint"
      />
      <span className="min-w-0">
        <span className="block text-xs font-bold text-ink">
          I have examined the document and it appears genuine
        </span>
        <span className="mt-1 block text-2xs leading-relaxed text-slate">
          Check the PAN number matches the form, the photo and hologram are
          intact, and the card shows no sign of editing. Approval is recorded
          against your account.
        </span>
      </span>
    </label>
  );
}
