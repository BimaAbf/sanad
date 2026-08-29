/**
 * Tailwind preset — the design tokens from docs/06-frontend-ux.md 2.
 *
 * Values are transcribed verbatim from that document and are asserted against it
 * by apps/web/src/tokens.test.ts. Every foreground/background pair in the brand
 * ramp meets WCAG AAA (>= 7:1); do not adjust one without re-checking.
 */

/** @type {import('tailwindcss').Config} */
const preset = {
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#1F6F5C", soft: "#E4F2EE" },
        accent: { DEFAULT: "#E8873A", soft: "#FDF0E4" },
        ink: { DEFAULT: "#16211E", muted: "#4A5A55" },
        surface: { DEFAULT: "#FFFFFF", alt: "#F7F9F8" },
        border: "#D6E0DC",

        // Semantic — deliberately NOT red/green. Red reads as failure and this
        // product has no failure states.
        growing: "#2E7D6B",
        practising: "#C77E1F",
        resting: "#7A8B86",
        attention: "#8B4A6B",

        // Child palette — saturated but not fluorescent.
        k: {
          red: "#D93A2B",
          blue: "#1C6BBF",
          yellow: "#F0B429",
          green: "#2E8B4A",
          purple: "#7B4FA8",
          orange: "#E87722",
          pink: "#D9538C",
          brown: "#8B5E3C",
          black: "#2B2B2B",
          white: "#FFFFFF",
        },
      },

      fontSize: {
        xs: ["14px", { lineHeight: "1.9" }],
        sm: ["15px", { lineHeight: "1.9" }],
        base: ["17px", { lineHeight: "1.9" }],
        lg: ["20px", { lineHeight: "1.9" }],
        xl: ["24px", { lineHeight: "1.5" }],
        "2xl": ["30px", { lineHeight: "1.5" }],
        "3xl": ["38px", { lineHeight: "1.5" }],
        child: ["32px", { lineHeight: "2.1" }],
      },

      lineHeight: { tight: "1.5", base: "1.9", loose: "2.1" },

      spacing: {
        1: "4px",
        2: "8px",
        3: "12px",
        4: "16px",
        5: "24px",
        6: "32px",
        7: "48px",
        8: "64px",
        "touch-min": "48px",
        "touch-child": "88px",
      },

      borderRadius: { sm: "8px", md: "14px", lg: "22px", pill: "999px" },

      boxShadow: {
        1: "0 1px 2px rgb(22 33 30 / .06)",
        2: "0 4px 12px rgb(22 33 30 / .08)",
      },

      transitionDuration: { fast: "120ms", base: "220ms", slow: "400ms" },
      transitionTimingFunction: { misk: "cubic-bezier(.2,.7,.3,1)" },

      fontFamily: {
        sans: [
          "IBM Plex Sans Arabic",
          "Noto Sans Arabic",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
      },

      minHeight: { touch: "48px", "touch-child": "88px" },
      minWidth: { touch: "48px", "touch-child": "88px" },
    },
  },
  plugins: [],
};

export default preset;
