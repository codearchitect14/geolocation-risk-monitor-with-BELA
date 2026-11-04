// Full-page screenshots at the five review widths for visual inspection: reports/screens/<page>-<width>.png
import fs from "node:fs";
import { chromium } from "@playwright/test";

const base = process.env.WEB_URL ?? "http://localhost:3000";
const pages = {
  home: "/",
  platform: "/platform",
  pricing: "/pricing",
  methodology: "/methodology",
  article: "/resources/exposure-scoring",
  industry: "/industries/energy-utilities",
  contact: "/contact",
  login: "/login",
};
const widths = [375, 768, 1024, 1440, 1920];
fs.mkdirSync("reports/screens", { recursive: true });
const browser = await chromium.launch();
for (const w of widths) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  for (const [name, path] of Object.entries(pages)) {
    await page.goto(base + path);
    await page.waitForLoadState("load");
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += 600) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 60));
      }
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `reports/screens/${name}-${w}.png`, fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (overflow) console.log(`HORIZONTAL OVERFLOW ${name} @${w}`);
  }
  await ctx.close();
}
await browser.close();
console.log("screens done");
