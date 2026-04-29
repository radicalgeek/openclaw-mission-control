/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}", "./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["var(--font-heading)", "sans-serif"],
        body: ["var(--font-body)", "sans-serif"],
        display: ["var(--font-display)", "serif"],
      },
      colors: {
        brand: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          soft: "var(--accent-soft)",
        },
        // Semantic tokens — driven by CSS vars set in src/lib/branding.tsx.
        // Use as bg-success-soft, text-success, border-success, etc. The
        // -soft suffix is the rgba-tinted bg; bare token is the saturated fg.
        success: {
          DEFAULT: "var(--success-fg)",
          soft: "var(--success-bg)",
          border: "var(--success-border)",
        },
        warning: {
          DEFAULT: "var(--warning-fg)",
          soft: "var(--warning-bg)",
          border: "var(--warning-border)",
        },
        danger: {
          DEFAULT: "var(--danger-fg)",
          soft: "var(--danger-bg)",
          border: "var(--danger-border)",
        },
        info: {
          DEFAULT: "var(--info-fg)",
          soft: "var(--info-bg)",
          border: "var(--info-border)",
        },
        neutral: {
          DEFAULT: "var(--neutral-fg)",
          soft: "var(--neutral-bg)",
          border: "var(--neutral-border)",
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
