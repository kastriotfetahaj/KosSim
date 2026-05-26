import type { Config } from "tailwindcss";

export default {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        "sleek-fill": "#1A1E1F",
        "sleek-background": "#181B1F",
        "sleek-details-subtle": "#2D343D",
        "sleek-details": "#878787",
        "cyan": "#00ffff",
        "yellow": "#ffff00",
        "pink": "#ff00ff",
      },
      fontFamily: {
        saiba: "var(--font-saiba-45)"
      }
    },
  },
  plugins: [require('@tailwindcss/typography')],
} satisfies Config;
