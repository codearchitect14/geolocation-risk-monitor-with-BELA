// Lighthouse (desktop preset) for key pages. Saves reports/lighthouse-<page>.json and prints scores.
// Gates: performance >= 90 (home), accessibility >= 95, cumulative layout shift 0.1 or less.
import fs from "node:fs";
import { chromium } from "@playwright/test";
import * as chromeLauncher from "chrome-launcher";
import lighthouse, { desktopConfig } from "lighthouse";

const base = process.env.WEB_URL ?? "http://localhost:3000";
const pages = {
  home: "/",
  platform: "/platform",
  pricing: "/pricing",
  article: "/resources/exposure-scoring",
  contact: "/contact",
  login: "/login",
};
fs.mkdirSync("reports", { recursive: true });
const chrome = await chromeLauncher.launch({
  chromePath: chromium.executablePath(),
  chromeFlags: ["--headless=new", "--no-sandbox"],
});
let failed = false;
for (const [name, path] of Object.entries(pages)) {
  const runner = await lighthouse(
    base + path,
    { port: chrome.port, output: "json", logLevel: "error" },
    desktopConfig,
  );
  const lhr = runner.lhr;
  fs.writeFileSync(`reports/lighthouse-${name}.json`, JSON.stringify(lhr));
  const s = (k) => Math.round((lhr.categories[k]?.score ?? 0) * 100);
  const cls = lhr.audits["cumulative-layout-shift"].numericValue;
  const lcp = Math.round(lhr.audits["largest-contentful-paint"].numericValue);
  console.log(
    `${name.padEnd(9)} perf ${s("performance")}  a11y ${s("accessibility")}  best ${s("best-practices")}  seo ${s("seo")}  CLS ${cls.toFixed(3)}  LCP ${lcp} ms`,
  );
  if (s("accessibility") < 95 || cls > 0.1 || (name === "home" && s("performance") < 90)) failed = true;
}
await chrome.kill();
process.exit(failed ? 1 : 0);
