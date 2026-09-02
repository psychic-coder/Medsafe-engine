import type { Config } from "tailwindcss";

/**
 * Design tokens for the medsafe console.
 *
 * The palette is built around one idea: a result's *epistemic status* is the most important thing
 * on the screen. Three states get three treatments — confirmed (solid ink), needs a human (hatched),
 * and not checked (hollow, dashed, desaturated). `unknown` is deliberately a neutral slate rather
 * than red or green, because a coverage gap is neither an alarm nor a reassurance, and colouring it
 * as either would misreport it.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#12212E",
          muted: "#41525C",
          faint: "#6E7F88",
        },
        paper: "#EEF1F0",
        surface: "#FFFFFF",
        rule: {
          DEFAULT: "#C3CDD1",
          strong: "#9BAAB1",
        },
        // Functional signal colours. Each maps to exactly one meaning in the API contract.
        severe: { DEFAULT: "#A3182A", wash: "#F7E7E9" },
        caution: { DEFAULT: "#8A5B0C", wash: "#F8EEDD" },
        verified: { DEFAULT: "#1B6153", wash: "#E1EDE9" },
        unknown: { DEFAULT: "#5F7078", wash: "#E7EBEC" },
      },
      fontFamily: {
        display: ["Archivo", "Archivo Fallback", "system-ui", "sans-serif"],
        prose: ["'Source Serif 4'", "Georgia", "serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        tiny: ["0.75rem", { lineHeight: "1.125rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lede: ["1.0625rem", { lineHeight: "1.7rem" }],
        title: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.015em" }],
        display: ["2.125rem", { lineHeight: "2.25rem", letterSpacing: "-0.03em" }],
      },
      borderRadius: {
        // Two radii only: sheets are square-ish, controls are softer. Hierarchy, not decoration.
        sheet: "3px",
        control: "6px",
      },
      backgroundImage: {
        // The signature surface: "a human has not signed this off".
        hatch:
          "repeating-linear-gradient(135deg, rgba(138,91,12,0.13) 0 6px, transparent 6px 12px)",
        "hatch-quiet":
          "repeating-linear-gradient(135deg, rgba(95,112,120,0.12) 0 5px, transparent 5px 11px)",
      },
      maxWidth: {
        measure: "68ch",
      },
    },
  },
  plugins: [],
};

export default config;
