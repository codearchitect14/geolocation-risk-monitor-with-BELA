// Automated screenshots of the marketing site and, when sign-in details are given, the product application.
//
//   node scripts/capture-screenshots.mjs                         marketing pages only
//   DEMO_EMAIL=demo-viewer@example.com DEMO_PASSWORD=... node scripts/capture-screenshots.mjs
//
// Needs the web application and the API running (make demo). Output: reports/screenshots/<name>.png at 1440 x 900 (marketing
// pages are full height). The sign-in password is read from the environment and is never written anywhere. Only demonstration data
// appears in the product screens.
import fs from "node:fs";
import { chromium } from "@playwright/test";

const base = process.env.WEB_URL ?? "http://127.0.0.1:3000";
const out = process.env.OUT ?? "reports/screenshots";
const marketing = {
  home: "/",
  platform: "/platform",
  pricing: "/pricing",
  methodology: "/methodology",
  security: "/security",
  developers: "/developers",
  login: "/login",
};
const product = {
  "app-overview": "/app",
  "app-map": "/app/map?window=30d",
  "app-incidents": "/app/incidents",
  "app-alerts": "/app/alerts",
  "app-assets": "/app/assets",
  "app-sources": "/app/sources",
  "app-analytics": "/app/analytics",
};

fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
// The cookie notice would cover the bottom of every shot; mark it as acknowledged.
await context.addInitScript(() => window.localStorage.setItem("ms_notice_ack", "1"));
const page = await context.newPage();

async function settle() {
  await page.waitForLoadState("load");
  await page.waitForLoadState("networkidle").catch(() => undefined);
  try {
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += 600) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 50));
      }
      window.scrollTo(0, 0);
    });
  } catch {
    await page.waitForLoadState("load"); // a client side redirect replaced the page while scrolling; capture where it landed
  }
  await page.waitForTimeout(1200);
}

for (const [name, path] of Object.entries(marketing)) {
  await page.goto(base + path);
  await settle();
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  console.log("captured", name);
}

const email = process.env.DEMO_EMAIL;
const password = process.env.DEMO_PASSWORD;
if (email && password) {
  const signIn = () => context.request.post(`${base}/api/v1/auth/login`, { data: { email, password } });
  const res = await signIn();
  if (!res.ok()) {
    console.error(`sign-in failed (${res.status()}); product screens skipped`);
  } else {
    for (const [name, path] of Object.entries(product)) {
      await page.goto(base + path);
      await settle();
      if (page.url().includes("/login")) {
        await signIn(); // the session was lost (for example a refresh that arrived at the rate limit); sign in again once
        await page.goto(base + path);
        await settle();
      }
      await page.waitForTimeout(1500); // data and map tiles
      if (await page.getByText("Too many requests").count()) {
        await page.waitForTimeout(20_000); // the per-address limit; wait for the window to pass, then load again
        await page.reload();
        await settle();
        await page.waitForTimeout(1500);
      }
      await page.screenshot({ path: `${out}/${name}.png` });
      console.log("captured", name);
    }
  }
} else {
  console.log("DEMO_EMAIL and DEMO_PASSWORD not set; product screens skipped");
}
await browser.close();
