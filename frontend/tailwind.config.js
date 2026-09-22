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
      transitionTimingFunction: {
        // The house curve: fast to start, settling rather than stopping dead.
        glide: 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      transitionDuration: {
        micro: '120ms',
        base: '220ms',
        slow: '420ms',
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
        // Scroll reveal: small travel, so it reads as arriving rather than as
        // the page assembling itself.
        reveal: {
          '0%': { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Route change. Fires constantly, so it is short and shallow.
        'page-in': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pop: {
          '0%': { transform: 'scale(0.86)' },
          '60%': { transform: 'scale(1.06)' },
          '100%': { transform: 'scale(1)' },
        },
        'slide-down': {
          '0%': { opacity: '0', transform: 'translateY(-4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // A grid arriving as a set: scale plus travel, so the tiles settle
        // into place instead of merely fading.
        'tile-in': {
          '0%': { opacity: '0', transform: 'translateY(18px) scale(0.92)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'label-in': {
          '0%': { opacity: '0', transform: 'translateX(-6px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        // Landing atmosphere: slow, large, low contrast. Weather, not motion.
        drift: {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '33%': { transform: 'translate3d(3%, -4%, 0) scale(1.06)' },
          '66%': { transform: 'translate3d(-3%, 3%, 0) scale(0.97)' },
        },
        'gradient-pan': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'shine-sweep': {
          '0%': { transform: 'translateX(-120%) skewX(-16deg)', opacity: '0' },
          '35%': { opacity: '1' },
          '100%': { transform: 'translateX(220%) skewX(-16deg)', opacity: '0' },
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
        reveal: 'reveal 520ms cubic-bezier(0.16,1,0.3,1) both',
        'page-in': 'page-in 260ms cubic-bezier(0.16,1,0.3,1) both',
        pop: 'pop 260ms cubic-bezier(0.16,1,0.3,1)',
        'slide-down': 'slide-down 180ms cubic-bezier(0.16,1,0.3,1) both',
        'tile-in': 'tile-in 560ms cubic-bezier(0.22,1.2,0.36,1) both',
        'label-in': 'label-in 400ms cubic-bezier(0.16,1,0.3,1) both',
        drift: 'drift 22s ease-in-out infinite',
        'drift-slow': 'drift 34s ease-in-out infinite',
        'gradient-pan': 'gradient-pan 14s ease-in-out infinite',
        'shine-sweep': 'shine-sweep 900ms cubic-bezier(0.16,1,0.3,1)',
      },
    },
  },
  plugins: [],
};
