import type { Config } from "tailwindcss";

/**
 * Tailwind theme for Amazon Edge-Return (Requirement 17).
 *
 * The custom color tokens replicate the official Amazon web/mobile palette and
 * are reused across the customer-facing shell and the admin dashboard.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Customer-facing tokens (Req 17.1)
        amazonNavy: "#232F3E", // top nav bar
        amazonDark: "#131921", // secondary dark header band
        amazonOrange: "#FF9900", // accents
        amazonLink: "#007185", // text links
        amazonBg: "#EAEDED", // page background
        // Admin dashboard token (Req 17.3)
        adminSlate: "#020617", // slate-950 full-viewport dark background
        // Body text color that meets >= 4.5:1 contrast on light backgrounds (Req 17.4)
        amazonInk: "#0F1111",
      },
      backgroundImage: {
        // Primary button gradient: top -> bottom (Req 17.2)
        "amazon-button": "linear-gradient(to bottom, #FFD814, #F7CA00)",
      },
      borderRadius: {
        // Primary button radius (Req 17.2)
        amazon: "8px",
      },
      keyframes: {
        // Sweeping scan line for the AI verification scan modal (Req 3.6).
        "ai-scan-sweep": {
          "0%": { top: "0%" },
          "100%": { top: "100%" },
        },
      },
      animation: {
        "ai-scan-sweep": "ai-scan-sweep 1.1s ease-in-out infinite alternate",
      },
    },
  },
  plugins: [],
};

export default config;
