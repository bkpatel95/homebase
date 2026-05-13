/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        masthead: ['"Playfair Display"', 'Georgia', 'serif'],
        serif: ['Georgia', '"Times New Roman"', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        paper: '#faf8f4',
        paperdark: '#f3efe6',
        ink: '#1a1a1a',
        inksoft: '#3a3a3a',
        rule: '#cfc8b8',
        accent: '#8a2a1f',
      },
    },
  },
  plugins: [],
};
