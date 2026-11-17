// Harness build for the real-browser check of «تصویر به کد» (backend/apps/img2code/tests_browser.py).
// The REAL page component runs in Chromium with the panel's real CSS (Tailwind); axios is wired to a Python function that answers with the real Django views.
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  root: __dirname,
  base: "./",
  plugins: [react(), tailwindcss()],
  build: { outDir: process.env.I2C_HARNESS_OUT || "/tmp/i2c-harness-out", emptyOutDir: true, assetsInlineLimit: 400000, chunkSizeWarningLimit: 4000 },
});
