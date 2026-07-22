import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    exclude: ["@fontsource/ibm-plex-mono", "@fontsource/ibm-plex-sans"],
  },
  server: {
    host: true,
  },
});
