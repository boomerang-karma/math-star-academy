/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Mirrors the CSP CloudFront sends (infra/leadintel_infra/stacks/web.py) minus the Cognito
// hosts, so `vite preview` and the Playwright suite catch anything a strict CSP would block.
const PREVIEW_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

// The SPA calls same-origin /api in every environment: CloudFront routes it in AWS,
// this proxy routes it to the local API (scripts/dev/run_api.sh) in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    headers: { "Content-Security-Policy": PREVIEW_CSP },
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    sourcemap: false,
    target: "es2022",
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
