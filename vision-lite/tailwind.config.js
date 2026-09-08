/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        serif: ['"Instrument Serif"', 'Georgia', 'serif'],
      },
      colors: {
        ink: {
          950: '#000000',
          900: '#050505',
          800: '#0a0a0b',
          700: '#141416',
          600: '#1c1c1f',
          500: '#28282A',
          400: '#3a3a3d',
          300: '#5a5a5e',
          200: '#9A9A9A',
          100: '#D8D8D8',
          50: '#F5F5F5',
        },
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-down': {
          '0%': { opacity: '0', transform: 'translateY(-12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'slide-in': {
          '0%': { opacity: '0', transform: 'translateX(-12px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'orb-pulse': {
          '0%, 100%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.08)', opacity: '0.85' },
        },
        'orb-rotate': {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        'shine': {
          '0%': { transform: 'translateX(-150%)' },
          '100%': { transform: 'translateX(250%)' },
        },
        'scan': {
          '0%': { top: '0%' },
          '100%': { top: '100%' },
        },
        'highlight-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255,255,255,0.4)' },
          '50%': { boxShadow: '0 0 0 6px rgba(255,255,255,0)' },
        },
        'check-stroke': {
          '0%': { strokeDashoffset: '24' },
          '100%': { strokeDashoffset: '0' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.6s ease-out both',
        'fade-up': 'fade-up 0.6s ease-out both',
        'fade-down': 'fade-down 0.6s ease-out both',
        'scale-in': 'scale-in 0.5s ease-out both',
        'slide-in': 'slide-in 0.4s ease-out both',
        'orb-pulse': 'orb-pulse 2s ease-in-out infinite',
        'orb-rotate': 'orb-rotate 8s linear infinite',
        'shine': 'shine 0.8s ease-out',
        'scan': 'scan 2s ease-in-out infinite',
        'highlight-pulse': 'highlight-pulse 1.6s ease-in-out infinite',
        'check-stroke': 'check-stroke 0.4s ease-out both',
      },
    },
  },
  plugins: [],
};
