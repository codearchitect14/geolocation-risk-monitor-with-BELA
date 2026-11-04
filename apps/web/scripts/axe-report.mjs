// Runs axe-core against every route at desktop and mobile widths and saves reports/axe.json. Exit code 1 on any violation.
import fs from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";
import { ROUTES } from "../e2e/routes.mjs";

const base = process.env.WEB_URL ?? "http://localhost:3000";
const widths = [375, 1440];
const browser = await chromium.launch();
const report = [];
for (const width of widths) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  for (const route of ROUTES) {
    await page.goto(base + route);
    await page.waitForLoadState("load");
    await page.waitForTimeout(400);
    const res = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    report.push({
      route,
      width,
      violations: res.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.slice(0, 4).map((n) => n.target.join(" ")),
      })),
    });
  }
  await context.close();
}
await browser.close();
fs.mkdirSync("reports", { recursive: true });
fs.writeFileSync(
  "reports/axe.json",
  JSON.stringify({ generated: new Date().toISOString(), base, results: report }, null, 1) + "\n",
);
const bad = report.filter((r) => r.violations.length);
const summary = {};
for (const r of bad)
  for (const v of r.violations) (summary[v.id] ??= new Set()).add(`${r.width}:${v.nodes[0]}`);
for (const [id, set] of Object.entries(summary)) console.log(id, [...set].slice(0, 4).join(" ; "));
console.log(`axe: ${report.length} page runs, ${bad.length} with violations`);
process.exit(bad.length ? 1 : 0);
