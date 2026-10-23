import { useState } from 'react';

import { bankCardTheme } from '../domain/BankLogo';
import { CARD_THEMES, THEME_CHOICES } from '../domain/cardThemes';
import { cx } from '../ui';
import { useToast } from '../../context/ToastContext';

/**
 * Choose a card's colours. Saving a theme changes how the card is drawn and
 * nothing else - no figure, status or verification moves with it.
 */
export default function ThemePicker({ card, onSave }) {
  const toast = useToast();
  const [saving, setSaving] = useState('');
  const current = card.theme || 'AUTO';
  const bank = bankCardTheme(card.issuer_id || null, card.issuer_bank) || CARD_THEMES.MATTE_BLACK;

  async function pick(value) {
    if (value === current || saving) return;
    setSaving(value);
    try {
      await onSave(value);
      toast.success('Card colours updated.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving('');
    }
  }

  return (
    <div>
      <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Card colours</p>
      <div className="mt-2 flex flex-wrap gap-2.5">
        {THEME_CHOICES.map(({ value, label }) => {
          const theme = value === 'AUTO' ? bank : CARD_THEMES[value];
          const selected = value === current;
          return (
            <button
              key={value}
              type="button"
              onClick={() => pick(value)}
              title={label}
              aria-label={label}
              aria-pressed={selected}
              className={cx(
                'group flex flex-col items-center gap-1 rounded-xl p-1 transition',
                selected ? 'ring-2 ring-ink' : 'hover:bg-mist',
                saving === value && 'animate-pulse',
              )}
            >
              <span
                className="h-8 w-12 rounded-lg shadow-sm transition-transform duration-base group-hover:scale-105"
                style={{ backgroundImage: `linear-gradient(135deg, ${theme.from}, ${theme.to})` }}
              />
              <span className="max-w-[56px] truncate text-[10px] text-slate">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
