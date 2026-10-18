import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // پنل زیرِ /panel/ ِ سایتِ یکپارچه (NMarketing) نشسته است
  base: "/panel/",
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // listen on IPv4 + IPv6 so localhost/127.0.0.1 and LAN devices all work
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
