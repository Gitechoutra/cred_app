import { bankCardTheme } from './BankLogo';

/**
 * Card colour themes. Purely visual: a theme never changes a figure, a status
 * or whether a card is verified - the server stores it apart from all three.
 *
 * AUTO paints a card in its issuing bank's logo colours (BankLogo's
 * BANK_CARD_THEMES). The others are palettes a holder can pick. The names
 * describe colours, not banks: these are suggested looks, not brand
 * specifications.
 */
export const CARD_THEMES = {
  MATTE_BLACK: { label: 'Matte black', from: '#2A2D2C', to: '#0A0C0B', accent: '#C9CED3', sheen: 'silver' },
  DEEP_BLUE: { label: 'Deep blue', from: '#0B5CAD', to: '#062E5A', accent: '#FFFFFF' },
  SUNSET: { label: 'Orange & blue', from: '#F06321', to: '#123A73', accent: '#FFB27A' },
  NAVY_SKY: { label: 'Navy & sky', from: '#1D3E8A', to: '#0F1F47', accent: '#7FD3FF' },
  BURGUNDY: { label: 'Burgundy', from: '#8E1F43', to: '#4A0B1F', accent: '#E66A8D' },
  BLUE_SILVER: { label: 'Blue & silver', from: '#2F7FD1', to: '#0F3F75', accent: '#D7E3EE', sheen: 'silver' },
  PURPLE: { label: 'Royal purple', from: '#6B3FD1', to: '#2E1466', accent: '#C3A6FF' },
  TEAL: { label: 'Deep teal', from: '#0E8C83', to: '#04403D', accent: '#7FF0DF' },
  AURORA: { label: 'Aurora', from: '#3B2A8F', to: '#0B5E6E', accent: '#00F5B8' },
};

export const THEME_CHOICES = [
  { value: 'AUTO', label: 'Bank colours' },
  ...Object.entries(CARD_THEMES).map(([value, theme]) => ({ value, label: theme.label })),
];

/** The CRED-style default for a bank with no logo theme. */
const FALLBACK = CARD_THEMES.MATTE_BLACK;

/** The colours a card is drawn in. */
export function resolveTheme(card) {
  const chosen = card?.theme && card.theme !== 'AUTO' ? CARD_THEMES[card.theme] : null;
  if (chosen) return chosen;
  return bankCardTheme(card?.issuer_id || null, card?.issuer_bank) || FALLBACK;
}

/**
 * One shape for both kinds of card, so a tile or a dashboard row does not
 * care whether CashU set the limit or the holder typed it.
 */
export function normaliseCard(card) {
  const manual = card.kind === 'MANUAL';
  return {
    ...card,
    id: manual ? card.manual_card_id : card.card_id,
    manual,
    path: manual ? `/cards/manual/${card.manual_card_id}` : `/cards/${card.card_id}`,
    limit: manual ? card.credit_limit : card.card_limit,
    available: manual ? card.available_credit : (card.available_limit ?? card.card_limit),
    outstanding: manual ? card.outstanding_balance : card.outstanding_amount,
    minimumDue: manual ? card.minimum_due : card.minimum_due_amount,
    totalDue: manual ? card.total_due : card.current_due_amount,
    dueDate: manual ? card.payment_due_date : card.next_due_date,
  };
}
