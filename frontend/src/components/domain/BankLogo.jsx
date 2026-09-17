import { useState } from 'react';
import { cx } from '../ui';

// Mapping of bank IDs / aliases to official authentic vector SVG files in public/banks/
const OFFICIAL_BANK_LOGOS = {
  sbi: '/banks/sbicard.svg',
  'sbi-card': '/banks/sbicard.svg',
  hdfc: '/banks/hdfc.svg',
  icici: '/banks/icici.svg',
  axis: '/banks/axis.svg',
  kotak: '/banks/kotak.svg',
  union: '/banks/union.svg',
  amex: '/banks/amex.svg',
  'american-express': '/banks/amex.svg',
  yes: '/banks/yes.svg',
  indusind: '/banks/indusind.svg',
  pnb: '/banks/pnb.svg',
  rbl: '/banks/rbl.svg',
  canara: '/banks/canara.svg',
  federal: '/banks/federal.svg',
  idfc: '/banks/idfc.svg',
};

// Resolves the official logo URL for a bank given its ID or Name.
function getOfficialLogoUrl(bankId, bankName) {
  const normalizedId = (bankId || '').toLowerCase().trim();
  if (OFFICIAL_BANK_LOGOS[normalizedId]) {
    return OFFICIAL_BANK_LOGOS[normalizedId];
  }

  const normalizedName = (bankName || '').toLowerCase().trim();
  if (normalizedName.includes('sbi') || normalizedName.includes('state bank')) return OFFICIAL_BANK_LOGOS.sbi;
  if (normalizedName.includes('hdfc')) return OFFICIAL_BANK_LOGOS.hdfc;
  if (normalizedName.includes('icici')) return OFFICIAL_BANK_LOGOS.icici;
  if (normalizedName.includes('axis')) return OFFICIAL_BANK_LOGOS.axis;
  if (normalizedName.includes('kotak')) return OFFICIAL_BANK_LOGOS.kotak;
  if (normalizedName.includes('union')) return OFFICIAL_BANK_LOGOS.union;
  if (normalizedName.includes('amex') || normalizedName.includes('american express')) return OFFICIAL_BANK_LOGOS.amex;
  if (normalizedName.includes('yes')) return OFFICIAL_BANK_LOGOS.yes;
  if (normalizedName.includes('indusind')) return OFFICIAL_BANK_LOGOS.indusind;
  if (normalizedName.includes('pnb') || normalizedName.includes('punjab')) return OFFICIAL_BANK_LOGOS.pnb;
  if (normalizedName.includes('rbl')) return OFFICIAL_BANK_LOGOS.rbl;
  if (normalizedName.includes('canara')) return OFFICIAL_BANK_LOGOS.canara;
  if (normalizedName.includes('federal')) return OFFICIAL_BANK_LOGOS.federal;
  if (normalizedName.includes('idfc')) return OFFICIAL_BANK_LOGOS.idfc;

  return null;
}

/**
 * BankLogo Component
 *
 * Renders authentic official bank logos with proper aspect ratio handling
 * (accommodating wide horizontal bank wordmarks without shrinking them to tiny heights).
 */
export function BankLogo({
  bankId,
  bankName,
  className,
  size = 'md',
  isCardPreview = false,
  variant = 'badge', // 'badge' (list item) | 'popular' (grid card) | 'preview' (on card)
}) {
  const [imgError, setImgError] = useState(false);
  const logoUrl = getOfficialLogoUrl(bankId, bankName);

  // Styling based on context/variant
  let containerClasses = '';
  let imgClasses = 'h-full w-full object-contain pointer-events-none';

  if (variant === 'popular') {
    // Popular bank tile: wide aspect ratio so horizontal bank logos fill the space prominently
    containerClasses = 'h-11 w-full max-w-[130px] flex items-center justify-center px-1 py-0.5 rounded-lg';
    imgClasses = 'h-full max-h-9 w-auto max-w-full object-contain pointer-events-none';
  } else if (variant === 'preview' || isCardPreview) {
    // On the credit card preview: crisp, prominent white badge
    containerClasses = 'h-8 px-2.5 py-1 rounded-lg bg-white shadow-sm flex items-center justify-center shrink-0';
    imgClasses = 'h-full w-auto max-w-[90px] object-contain pointer-events-none';
  } else {
    // List item / search results: rectangular badge so logos have width to breathe
    const sizeMap = {
      xs: 'h-7 w-12 rounded-lg p-0.5',
      sm: 'h-8 w-16 rounded-lg p-1',
      md: 'h-11 w-20 sm:w-24 rounded-xl p-1.5',
      lg: 'h-12 w-28 rounded-xl p-1.5',
    };
    containerClasses = cx(
      'bg-white border border-line/70 shadow-sm flex items-center justify-center shrink-0',
      sizeMap[size] || sizeMap.md,
    );
  }

  // Fallback monogram for custom unlisted banks or broken images
  if (!logoUrl || imgError) {
    const initials = (bankName || 'Bank')
      .split(/\s+/)
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase();

    return (
      <div
        className={cx(
          'grid place-items-center font-bold tracking-wider shrink-0 transition select-none shadow-sm rounded-xl',
          isCardPreview || variant === 'preview'
            ? 'h-8 px-3 bg-white/20 text-white border border-white/30 backdrop-blur-sm'
            : variant === 'popular'
            ? 'h-10 w-16 bg-ink text-mint'
            : 'h-11 w-14 bg-gradient-to-br from-ink-700 to-ink text-mint border border-line',
          className,
        )}
      >
        <span className="text-xs">{initials || 'BK'}</span>
      </div>
    );
  }

  return (
    <div className={cx(containerClasses, className)}>
      <img
        src={logoUrl}
        alt={`${bankName || 'Bank'} logo`}
        onError={() => setImgError(true)}
        className={imgClasses}
        loading="eager"
      />
    </div>
  );
}
