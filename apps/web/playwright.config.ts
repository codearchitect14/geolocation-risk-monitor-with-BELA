import { defineConfig, devices } from "@playwright/test";

const desktop = { viewport: { width: 1440, height: 900 } };

// `chromium` is the default and what CI runs on every change. The others are the cross-browser pass (`npm run e2e:cross`):
// installed Chrome, Firefox, and WebKit (the engine of Safari). Edge shares the Chromium engine; its channel is available
// as `msedge` on machines that have Edge installed.
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3000", trace: "off" },
  projects: [
    { name: "chromium", use: { browserName: "chromium", ...desktop } },
    { name: "chrome", use: { ...devices["Desktop Chrome"], channel: "chrome", ...desktop } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], ...desktop } },
    { name: "webkit", use: { ...devices["Desktop Safari"], ...desktop } },
    { name: "msedge", use: { ...devices["Desktop Edge"], channel: "msedge", ...desktop } },
  ],
});
