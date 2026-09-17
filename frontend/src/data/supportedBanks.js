/**
 * Supported credit-card issuing banks in India.
 *
 * Each bank entry contains metadata for routing, card branding, search keywords,
 * and default card BIN prefix used for sample hints and linking fallbacks.
 */

export const SUPPORTED_BANKS = [
  // ── Popular banks (suggested directly below search bar) ──────────────────
  {
    id: 'sbi',
    name: 'SBI Card',
    shortName: 'SBI Card',
    brandColor: '#22409A',
    popular: true,
    sampleBin: '421822',
    networks: ['Visa', 'Mastercard', 'RuPay'],
    keywords: ['sbi', 'sbi card', 'state bank of india', 'state bank'],
  },
  {
    id: 'hdfc',
    name: 'HDFC Bank',
    shortName: 'HDFC Bank',
    brandColor: '#004C8F',
    popular: true,
    sampleBin: '455614',
    networks: ['Visa', 'Mastercard', 'RuPay'],
    keywords: ['hdfc', 'hdfc bank', 'housing development finance'],
  },
  {
    id: 'icici',
    name: 'ICICI Bank',
    shortName: 'ICICI Bank',
    brandColor: '#AE275F',
    popular: true,
    sampleBin: '462938',
    networks: ['Visa', 'Mastercard', 'RuPay'],
    keywords: ['icici', 'icici bank', 'industrial credit'],
  },
  {
    id: 'axis',
    name: 'Axis Bank',
    shortName: 'Axis Bank',
    brandColor: '#97144D',
    popular: true,
    sampleBin: '414767',
    networks: ['Visa', 'Mastercard', 'RuPay'],
    keywords: ['axis', 'axis bank', 'uti'],
  },
  {
    id: 'kotak',
    name: 'Kotak Mahindra Bank',
    shortName: 'Kotak',
    brandColor: '#ED1C24',
    popular: true,
    sampleBin: '434582',
    networks: ['Visa', 'Mastercard'],
    keywords: ['kotak', 'kotak mahindra', 'kotak bank'],
  },
  {
    id: 'union',
    name: 'Union Bank of India',
    shortName: 'Union Bank',
    brandColor: '#E21E26',
    popular: true,
    sampleBin: '517618',
    networks: ['Visa', 'RuPay'],
    keywords: ['union', 'union bank', 'union bank of india', 'ubi'],
  },

  // ── Other supported credit card issuers ──────────────────────────────────
  {
    id: 'amex',
    name: 'American Express',
    shortName: 'Amex',
    brandColor: '#006FCF',
    popular: false,
    sampleBin: '377860',
    networks: ['Amex'],
    keywords: ['amex', 'american express', 'centurion'],
  },
  {
    id: 'indusind',
    name: 'IndusInd Bank',
    shortName: 'IndusInd',
    brandColor: '#8B1C3F',
    popular: false,
    sampleBin: '461797',
    networks: ['Visa', 'Mastercard'],
    keywords: ['indusind', 'indusind bank'],
  },
  {
    id: 'idfc',
    name: 'IDFC FIRST Bank',
    shortName: 'IDFC FIRST',
    brandColor: '#9C1D26',
    popular: false,
    sampleBin: '418228',
    networks: ['Visa', 'Mastercard'],
    keywords: ['idfc', 'idfc first', 'idfc first bank'],
  },
  {
    id: 'yes',
    name: 'Yes Bank',
    shortName: 'Yes Bank',
    brandColor: '#00518F',
    popular: false,
    sampleBin: '465558',
    networks: ['Visa', 'Mastercard', 'RuPay'],
    keywords: ['yes', 'yes bank'],
  },
  {
    id: 'pnb',
    name: 'Punjab National Bank',
    shortName: 'PNB',
    brandColor: '#4B286D',
    popular: false,
    sampleBin: '607600',
    networks: ['RuPay', 'Visa'],
    keywords: ['pnb', 'punjab national bank', 'punjab'],
  },
  {
    id: 'rbl',
    name: 'RBL Bank',
    shortName: 'RBL',
    brandColor: '#D31245',
    popular: false,
    sampleBin: '433327',
    networks: ['Visa', 'Mastercard'],
    keywords: ['rbl', 'rbl bank', 'ratnakar bank'],
  },
  {
    id: 'canara',
    name: 'Canara Bank',
    shortName: 'Canara Bank',
    brandColor: '#0091DF',
    popular: false,
    sampleBin: '405021',
    networks: ['Visa', 'RuPay', 'Mastercard'],
    keywords: ['canara', 'canara bank'],
  },
  {
    id: 'federal',
    name: 'Federal Bank',
    shortName: 'Federal Bank',
    brandColor: '#003366',
    popular: false,
    sampleBin: '409414',
    networks: ['Visa', 'Mastercard'],
    keywords: ['federal', 'federal bank', 'fed'],
  },
  {
    id: 'bob',
    name: 'Bank of Baroda',
    shortName: 'BOB Financial',
    brandColor: '#F15A22',
    popular: false,
    sampleBin: '508227',
    networks: ['Visa', 'RuPay'],
    keywords: ['bob', 'bank of baroda', 'baroda'],
  },
  {
    id: 'scb',
    name: 'Standard Chartered',
    shortName: 'StanChart',
    brandColor: '#0473EA',
    popular: false,
    sampleBin: '512345',
    networks: ['Visa', 'Mastercard'],
    keywords: ['standard chartered', 'stan chart', 'scb'],
  },
  {
    id: 'au',
    name: 'AU Small Finance Bank',
    shortName: 'AU Bank',
    brandColor: '#5C2D91',
    popular: false,
    sampleBin: '530598',
    networks: ['Visa'],
    keywords: ['au', 'au small finance', 'au bank', 'au sfb'],
  },
  {
    id: 'hsbc',
    name: 'HSBC',
    shortName: 'HSBC',
    brandColor: '#DB0011',
    popular: false,
    sampleBin: '412967',
    networks: ['Visa'],
    keywords: ['hsbc', 'hongkong and shanghai'],
  },
];

/**
 * Match a search query against bank name, short name, and keywords.
 */
export function searchBanks(query, banks = SUPPORTED_BANKS) {
  const clean = (query || '').trim().toLowerCase();
  if (!clean) return [];

  return banks.filter((bank) => {
    if (bank.name.toLowerCase().includes(clean)) return true;
    if (bank.shortName.toLowerCase().includes(clean)) return true;
    return bank.keywords.some((k) => k.toLowerCase().includes(clean));
  });
}
