/** @tailwind config
 *  Locked design tokens — see docs/DESIGN.md ("Field Museum of Ideas", v1).
 *  Concept: a museum accession catalogue for hackathon projects.
 *  Rules that matter: hairline rules do elevation (no shadows); one signal hue
 *  (specimen vermilion); sector hues are DATA ONLY; dark is sanctioned for the
 *  Atlas viewport alone; no violet/indigo/fuchsia anywhere; no gradient text.
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Museum-wall ladder: card stock, wall, recess
        bone: {
          50: '#fbf9f4',
          100: '#f4f1ea',
          200: '#ece7db',
          300: '#ddd6c6',
          400: '#c7bda6',
          500: '#a89c81',
          600: '#877c63',
          700: '#665e4b',
          800: '#413c30',
          900: '#221f19',
          950: '#14120f',
        },
        // Specimen vermilion: the single signal colour (CTAs, active states)
        signal: {
          100: '#fbdccf',
          300: '#efa284',
          500: '#c9421a',
          600: '#b23a17',
          700: '#8f2f12',
          900: '#431508',
        },
        // Brass: quiet metadata accent (accession numbers, leader dots, ticks)
        brass: {
          300: '#e2cb93',
          500: '#b28e3c',
          700: '#7c6220',
        },
        // Only inside the Atlas canvas
        gallery: {
          900: '#101010',
          950: '#0a0a0b',
        },
      },
      fontFamily: {
        display: ['"Newsreader"', 'Georgia', 'serif'],
        sans: ['"Public Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        sm: '3px',
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '10px',
        '2xl': '10px',
      },
      letterSpacing: { accession: '0.16em', label: '0.12em' },
      boxShadow: { none: 'none' },
    },
  },
  plugins: [],
}
