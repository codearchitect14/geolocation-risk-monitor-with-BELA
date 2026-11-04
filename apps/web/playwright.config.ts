import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3000", trace: "off" },
  projects: [{ name: "chromium", use: { browserName: "chromium", viewport: { width: 1440, height: 900 } } }],
});
