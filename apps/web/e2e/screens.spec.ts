import { test } from "@playwright/test";
import { signIn } from "./helpers";

/** Screenshots of application pages for visual review. Run with SCREENS=1; output goes to reports/screens (ignored by git). */
test.skip(!process.env.SCREENS, "set SCREENS=1 to capture screenshots");

const PAGES: [string, string][] = [
  ["overview", "/app"],
  ["map", "/app/map?window=30d"],
  ["assets", "/app/assets"],
  ["incidents", "/app/incidents?"],
  ["alerts", "/app/alerts"],
  ["zones", "/app/zones"],
  ["analytics", "/app/analytics"],
  ["settings", "/app/settings"],
];
const ADMIN: [string, string][] = [
  ["admin", "/app/admin"],
  ["billing", "/app/billing"],
];
const PLATFORM: [string, string][] = [
  ["revenue", "/app/platform/revenue"],
  ["pipeline", "/app/platform/analytics"],
];

for (const [who, list] of [
  ["mgr@example.org", PAGES],
  ["ta@example.org", ADMIN],
  ["pa@example.org", PLATFORM],
] as const)
  for (const width of [1440, 375])
    for (const [name, url] of list)
      test(`${name} @${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: width > 600 ? 900 : 800 });
        await signIn(page, who);
        await page.goto(url);
        await page.waitForTimeout(3500);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (overflow > 1) console.log(`OVERFLOW ${name} @${width}: ${overflow}px`);
        await page.screenshot({ path: `reports/screens/app-${name}-${width}.png`, fullPage: width > 600 });
      });
