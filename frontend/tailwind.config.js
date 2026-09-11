/**
 * CashU design tokens.
 *
 * White dominates; mint is punctuation. Mint on white fails WCAG AA below 18px,
 * so mint is reserved for fills, accents and large numerals - never body text.
 * Ink carries the text and the "card" surfaces.
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        mint: {
          DEFAULT: '#00F5B8',
          50: '#EAFFF9',
          100: '#CCFFF0',
          200: '#99FFE2',
          300: '#5CFCD1',
          400: '#1FF7C0',
          500: '#00F5B8',
          600: '#00C594',
          700: '#009170',
          800: '#00614B',
          900: '#003A2D',
        },
        ink: {
          DEFAULT: '#0A0F0D',
          800: '#141A18',
          700: '#1F2725',
          600: '#2C3634',
        },
        canvas: '#FFFFFF',
        mist: '#F4F6F5',
        line: '#E6EAE8',
        slate: {
          DEFAULT: '#6B7674',
          light: '#9AA5A3',
        },
        alert: '#EF4444',
        warn: '#F59E0B',
      },
      fontFamily: {
        sans: [
          'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI',
          'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif',
        ],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        xl: '1rem',
        '2xl': '1.25rem',
        '3xl': '1.75rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(10,15,13,0.04), 0 8px 24px -12px rgba(10,15,13,0.10)',
        lift: '0 4px 8px rgba(10,15,13,0.04), 0 16px 40px -16px rgba(10,15,13,0.16)',
        mint: '0 8px 24px -8px rgba(0,245,184,0.45)',
        sheet: '0 -8px 40px -12px rgba(10,15,13,0.18)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'sheet-up': {
          '0%': { transform: 'translateY(100%)' },
          '100%': { transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.92)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-14px)' },
        },
        'float-slow': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-22px)' },
        },
        sheen: {
          '0%': { transform: 'translateX(-120%) skewX(-18deg)' },
          '60%, 100%': { transform: 'translateX(320%) skewX(-18deg)' },
        },
        'deal-in': {
          '0%': { opacity: '0', transform: 'translateY(36px) rotate(0deg) scale(0.94)' },
          '100%': { opacity: '1' },
        },
        'rise-in': {
          '0%': { opacity: '0', transform: 'translateY(28px) scale(0.97)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.85)', opacity: '0.55' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
        marquee: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        'ring-draw': {
          '0%': { strokeDashoffset: '283' },
        },
      },
      animation: {
        'fade-up': 'fade-up 320ms cubic-bezier(0.16,1,0.3,1) both',
        'sheet-up': 'sheet-up 280ms cubic-bezier(0.16,1,0.3,1) both',
        'scale-in': 'scale-in 260ms cubic-bezier(0.16,1,0.3,1) both',
        shimmer: 'shimmer 1.6s infinite',
        float: 'float 6s ease-in-out infinite',
        'float-slow': 'float-slow 8s ease-in-out infinite',
        sheen: 'sheen 5.5s ease-in-out infinite',
        'deal-in': 'deal-in 900ms cubic-bezier(0.16,1,0.3,1) both',
        'rise-in': 'rise-in 700ms cubic-bezier(0.16,1,0.3,1) both',
        'pulse-ring': 'pulse-ring 2.6s ease-out infinite',
        marquee: 'marquee 28s linear infinite',
        'ring-draw': 'ring-draw 900ms cubic-bezier(0.16,1,0.3,1) both',
      },
    },
  },
  plugins: [],
};
