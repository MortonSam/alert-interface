import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // the one type scale (DESIGN.md): display for page titles and statements, headline for section titles, body, small
      fontSize: {
        display: ["clamp(32px, 3.6vw, 52px)", { lineHeight: "1.1", letterSpacing: "-0.01em" }],
        headline: ["clamp(20px, 1.9vw, 24px)", { lineHeight: "1.25", letterSpacing: "-0.005em" }],
        body: ["15px", { lineHeight: "1.6" }],
        small: ["12px", { lineHeight: "1.5" }],
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        border: "hsl(var(--border))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        ring: "hsl(var(--ring))",
        input: "hsl(var(--input))",
        cool: {
          DEFAULT: "hsl(var(--cool) / <alpha-value>)",
          foreground: "hsl(var(--cool-foreground))",
        },
        violet: {
          DEFAULT: "hsl(var(--violet) / <alpha-value>)",
          foreground: "hsl(var(--violet-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning) / <alpha-value>)",
          foreground: "hsl(var(--warning-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-ui)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],          // headings (Newsreader)
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        brand: ["var(--font-brand)", "Georgia", "serif"],          // the wordmark only (Playfair Display)
      },
    },
  },
  plugins: [],
};

export default config;
