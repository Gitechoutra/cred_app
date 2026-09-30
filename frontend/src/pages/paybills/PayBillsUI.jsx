import { useRef } from 'react';

import { cx } from '../../components/ui';
import { dateTime, money } from '../../utils/format';

/**
 * Pay Bills' shared vocabulary: category icons, the OTP boxes, the status of a
 * request, and the printable receipt.
 *
 * Every figure shown in any of these comes from the server. Nothing here adds a
 * fee or works out a total.
 */

/* ── Category icons ─────────────────────────────────────────────────────── */

// One stroke weight and one 24px grid, matching the AppShell icon family.
const CATEGORY_PATHS = {
  ELECTRICITY: ['M13 2.5L4.5 13.5H11l-1 8 8.5-11H12l1-8z'],
  WATER: ['M12 3.5s6 6.3 6 10.5a6 6 0 01-12 0c0-4.2 6-10.5 6-10.5z', 'M9.5 14.5a2.5 2.5 0 002.5 2.5'],
  GAS: ['M12 3c.8 2.8 4.5 4.8 4.5 9.2A4.5 4.5 0 017.5 12.2c0-2 1-3.3 2-4.2.1 2 1.1 3 2.3 3.2C11 8.5 11 6 12 3z', 'M7 21h10'],
  BROADBAND: ['M2.5 9a14 14 0 0119 0', 'M5.5 12.3a9.5 9.5 0 0113 0', 'M8.7 15.6a5 5 0 016.6 0', 'M12 19h.01'],
  MOBILE_POSTPAID: ['M8 2.5h8a1.5 1.5 0 011.5 1.5v16a1.5 1.5 0 01-1.5 1.5H8A1.5 1.5 0 016.5 20V4A1.5 1.5 0 018 2.5z', 'M11 18h2'],
  DTH: ['M3.5 7.5h17v11h-17z', 'M8.5 21.5h7', 'M8.5 3.5l3.5 4 3.5-4'],
  INSURANCE: ['M12 3l7.5 3v5.5c0 4.7-3.2 8-7.5 9.5-4.3-1.5-7.5-4.8-7.5-9.5V6L12 3z', 'M9 12l2 2 4-4'],
  EDUCATION: ['M2.5 9L12 4.5 21.5 9 12 13.5 2.5 9z', 'M6.5 11v4.5c2.8 2.3 8.2 2.3 11 0V11', 'M21.5 9v5'],
  RENT: ['M3.5 11L12 4l8.5 7', 'M5.5 9.5V20h13V9.5', 'M10 20v-5.5h4V20'],
  MEDICAL: ['M9.5 3.5h5v6h6v5h-6v6h-5v-6h-6v-5h6z'],
  OTHER: ['M6 3h12v18l-3-2-3 2-3-2-3 2V3z', 'M9 8h6M9 12h6'],
};

export function CategoryIcon({ category, className = 'h-5 w-5' }) {
  const paths = CATEGORY_PATHS[category] || CATEGORY_PATHS.OTHER;
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths.map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

/* ── Status ─────────────────────────────────────────────────────────────── */

/** One label and tone per state, used by every Pay Bills screen and receipt. */
export const BILL_STATUS = {
  AWAITING_OTP: { label: 'Awaiting OTP', tone: 'warn' },
  PROCESSING: { label: 'Processing', tone: 'warn' },
  PENDING: { label: 'Pending', tone: 'warn' },
  SUCCEEDED: { label: 'Successful', tone: 'good' },
  FAILED: { label: 'Failed', tone: 'alert' },
  REVERSED: { label: 'Reversed', tone: 'neutral' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral' },
  EXPIRED: { label: 'Expired', tone: 'neutral' },
};

export function billStatus(status) {
  return BILL_STATUS[status] || { label: status, tone: 'neutral' };
}

/* ── OTP ────────────────────────────────────────────────────────────────── */

/**
 * Six single-digit boxes, the same control as sign-in. Paste fills them all;
 * backspace on an empty box steps back.
 */
export function OtpBoxes({ digits, onChange, error, disabled, length = 6 }) {
  const inputs = useRef([]);

  function setDigit(index, value) {
    const char = value.replace(/\D/g, '').slice(-1);
    const next = [...digits];
    next[index] = char;
    onChange(next);
    if (char && index < length - 1) inputs.current[index + 1]?.focus();
  }

  function onKeyDown(index, event) {
    if (event.key === 'Backspace' && !digits[index] && index > 0) {
      inputs.current[index - 1]?.focus();
    }
    if (event.key === 'ArrowLeft' && index > 0) inputs.current[index - 1]?.focus();
    if (event.key === 'ArrowRight' && index < length - 1) inputs.current[index + 1]?.focus();
  }

  function onPaste(event) {
    const pasted = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, length);
    if (!pasted) return;
    event.preventDefault();
    onChange(Array.from({ length }, (_, i) => pasted[i] || ''));
    inputs.current[Math.min(pasted.length, length - 1)]?.focus();
  }

  return (
    <div
      className="flex justify-between gap-2"
      onPaste={onPaste}
      role="group"
      aria-label="One-time password"
    >
      {Array.from({ length }, (_, index) => (
        <input
          key={index}
          ref={(el) => { inputs.current[index] = el; }}
          value={digits[index] || ''}
          onChange={(event) => setDigit(index, event.target.value)}
          onKeyDown={(event) => onKeyDown(index, event)}
          inputMode="numeric"
          autoComplete={index === 0 ? 'one-time-code' : 'off'}
          autoFocus={index === 0}
          maxLength={1}
          disabled={disabled}
          aria-label={`Digit ${index + 1}`}
          className={cx(
            'money h-14 w-full min-w-0 rounded-xl border bg-canvas text-center',
            'text-xl font-semibold text-ink outline-none transition-all',
            'focus:border-ink/40 focus:ring-2 focus:ring-mint/20',
            error ? 'border-alert' : digits[index] ? 'border-ink/25' : 'border-line',
          )}
        />
      ))}
    </div>
  );
}

/* ── Receipt ────────────────────────────────────────────────────────────── */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/**
 * Open a self-contained receipt and hand it to the print dialog, where "Save
 * as PDF" is the download. A separate document rather than a print stylesheet
 * on the app, so the receipt prints the same whatever screen it came from.
 */
export function downloadReceipt(bill) {
  const rows = [
    ['Transaction ID', bill.reference],
    ['Status', billStatus(bill.status).label],
    ['Bill', bill.category_label],
    ['Provider', bill.provider],
    ['Bill / reference number', bill.bill_reference],
    ['Purpose', bill.purpose_label + (bill.purpose_note ? ` - ${bill.purpose_note}` : '')],
    ['Bill amount', money(bill.bill_amount)],
    [`Processing fee (${bill.fee_percent}%)`, money(bill.fee_amount)],
    ['GST on fee', money(bill.gst_amount)],
    ['Total credit utilised', money(bill.total_amount)],
    ['Paid to', bill.bank],
    ['Bank UTR', bill.utr || '-'],
    ['Requested', dateTime(bill.created_on)],
    ['Completed', bill.completed_at ? dateTime(bill.completed_at) : '-'],
  ];

  const html = `<!doctype html><html><head><meta charset="utf-8">
<title>CashU receipt ${escapeHtml(bill.reference)}</title>
<style>
  body{font-family:Inter,system-ui,sans-serif;color:#0A0F0D;max-width:560px;margin:32px auto;padding:0 20px}
  .brand{display:flex;align-items:center;gap:8px;font-weight:800;font-size:20px}
  .dot{width:12px;height:12px;border-radius:50%;background:#00F5B8}
  h1{font-size:15px;color:#6B7674;font-weight:600;margin:6px 0 24px}
  .amt{font-size:34px;font-weight:800;margin:0}
  table{width:100%;border-collapse:collapse;margin-top:20px}
  td{padding:9px 0;border-bottom:1px solid #E6EAE8;font-size:13px;vertical-align:top}
  td:first-child{color:#6B7674;width:46%}
  td:last-child{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
  p.note{font-size:11px;color:#6B7674;line-height:1.6;margin-top:22px}
</style></head><body>
<div class="brand"><span class="dot"></span>CashU</div>
<h1>Pay Bills receipt</h1>
<p class="amt">${escapeHtml(money(bill.bill_amount))}</p>
<table>${rows.map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join('')}</table>
<p class="note">Funded from your CashU credit line and repayable with your card statement.
GST is charged on the processing fee only. Keep this receipt for your records; quote the
transaction ID to support for any query.</p>
<script>window.onload=function(){window.print()}</script>
</body></html>`;

  const win = window.open('', '_blank', 'noopener=no,width=640,height=820');
  if (!win) return false;
  win.document.open();
  win.document.write(html);
  win.document.close();
  return true;
}
