import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // System stack first (Figtree/Inter-like), Thai fallback last.
        sans: [
          "Figtree",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "Noto Sans Thai",
          "Thonburi",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
