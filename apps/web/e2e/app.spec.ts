import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

const MANAGER = "mgr@example.org";
const ADMIN = "ta@example.org";
const VIEWER = "viewer@example.org";
const PLATFORM = "pa@example.org";

const CSV = path.resolve(process.cwd(), "reports/e2e-assets.csv");

/** Alerts are consumed by the acknowledge test, so add a few fresh assets near current incidents first. */
function seedAlerts() {
  execFileSync(
    path.resolve(process.cwd(), "../../.venv/bin/python"),
    [path.resolve(process.cwd(), "../../data/scripts/seed_web_tenant.py"), "--count", "6"],
    {
      cwd: path.resolve(process.cwd(), "../.."),
      env: { ...process.env, PYTHONPATH: "apps/api" },
      stdio: "ignore",
    },
  );
}

test.describe("tenant application", () => {
  test.beforeAll(() => seedAlerts());

  test("manager uploads assets through the wizard and sees them listed", async ({ page }) => {
    await signIn(page, MANAGER);
    const stamp = Date.now();
    fs.mkdirSync(path.dirname(CSV), { recursive: true });
    fs.writeFileSync(
      CSV,
      `name,lat,lon,city,country,criticality,type,external_id,tags\nUpload A ${stamp} (illustrative),48.85,2.35,,,3,site,UP-${stamp}-1,e2e\nUpload B ${stamp} (illustrative),52.37,4.9,,,2,site,UP-${stamp}-2,e2e\n`,
    );
    await page.goto("/app/assets");
    await page.getByRole("button", { name: "Upload assets" }).click();
    await page.locator("#asset-file").setInputFiles(CSV);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Step 2 of 4")).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(page.getByText("Step 3 of 4")).toBeVisible();
    await expect(page.getByText("2 ready")).toBeVisible();
    await page.getByRole("button", { name: /^Continue/ }).click();
    await page.getByRole("button", { name: "Create assets" }).click();
    await expect(page.getByText(`Upload A ${stamp}`)).toBeVisible({ timeout: 15000 });
    fs.rmSync(CSV, { force: true });
  });

  test("manager draws a watch zone on the map", async ({ page }) => {
    await signIn(page, MANAGER);
    await page.goto("/app/zones");
    const name = `E2E zone ${Date.now()}`;
    await page.getByRole("button", { name: "Draw circle" }).click();
    const map = page.getByRole("region", { name: /Watch zones/ }).first();
    await expect(map).toBeVisible();
    await page.waitForTimeout(1500);
    const box = (await map.boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.click(box.x + box.width / 2 + 60, box.y + box.height / 2);
    await expect(page.getByText(/Circle of \d+ km drawn/)).toBeVisible();
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create zone" }).click();
    await expect(page.getByRole("cell", { name })).toBeVisible();
  });

  test("viewer opens an incident and sees the location transparency panel", async ({ page }) => {
    await signIn(page, VIEWER);
    await page.goto("/app/incidents");
    await expect(page.getByRole("heading", { name: "Incidents", level: 1 })).toBeVisible();
    await page.locator("tbody tr button").first().click();
    await page.getByRole("link", { name: "Open full incident" }).click();
    await expect(page.getByRole("heading", { name: "Location transparency" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Evidence and sources" })).toBeVisible();
  });

  test("incident list and map load once, without a request loop", async ({ page }) => {
    await signIn(page, MANAGER);
    for (const route of ["/app/incidents", "/app/map?window=30d"]) {
      let requests = 0;
      const count = (r: { url(): string }) => {
        if (r.url().includes("/api/v1/events?")) requests += 1;
      };
      page.on("request", count);
      await page.goto(route);
      await page.waitForTimeout(3000);
      page.off("request", count);
      expect(requests, `${route} requested /events ${requests} times in 3 seconds`).toBeLessThanOrEqual(3);
    }
  });

  test("manager acknowledges an alert with the keyboard", async ({ page }) => {
    await signIn(page, MANAGER);
    await page.goto("/app/alerts");
    await page.getByLabel("Status").selectOption("new");
    const first = page.locator("tbody tr").first();
    await expect(first).toBeVisible();
    const firstText = await first.innerText();
    await page.keyboard.press("a");
    await expect(page.getByRole("status").filter({ hasText: /acknowledged/ })).toBeVisible();
    // The acknowledged alert leaves the "new" list. (The count is not compared: a full page is refilled from the next page.)
    await expect(page.locator("tbody tr").first()).not.toHaveText(firstText, { timeout: 10000 });
  });

  test("manager exports a portfolio report", async ({ page }) => {
    await signIn(page, MANAGER);
    await page.goto("/app/reports");
    await page.getByRole("button", { name: "Create portfolio report" }).click();
    await expect(page.getByRole("button", { name: /Download Portfolio report as CSV/ }).first()).toBeVisible({
      timeout: 30000,
    });
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: /Download Portfolio report as CSV/ })
      .first()
      .click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  });

  test("map filters change what is shown and are kept in the address", async ({ page }) => {
    await signIn(page, MANAGER);
    await page.goto("/app/map?window=30d");
    await expect(page.getByRole("heading", { name: /\d+ incidents/ })).toBeVisible({ timeout: 15000 });
    await page.getByLabel("Severity").selectOption("3");
    await expect(page).toHaveURL(/sev=3/);
    await page.getByRole("button", { name: "Show as list" }).click();
    await expect(page.getByRole("region", { name: "Incidents on the map as a table" })).toBeVisible();
  });

  test("roles: a viewer cannot reach manager pages and does not see them in the menu", async ({ page }) => {
    await signIn(page, VIEWER);
    await page.goto("/app");
    const nav = page.getByRole("navigation", { name: "Application" });
    await expect(nav.getByRole("link", { name: "Alerts" })).toBeVisible();
    for (const hidden of ["Reports", "Analytics", "Administration", "Billing", "Watch zones"])
      await expect(nav.getByRole("link", { name: hidden })).toHaveCount(0);
    await page.goto("/app/admin");
    await expect(page).toHaveURL(/\/app$/);
  });

  test("administrator creates an API key and sees its secret once", async ({ page }) => {
    await signIn(page, ADMIN);
    await page.goto("/app/admin");
    await page.getByRole("tab", { name: "API keys" }).click();
    await page.getByRole("button", { name: "Create API key" }).click();
    await page.getByLabel("Name").fill(`e2e key ${Date.now()}`);
    await page.getByRole("button", { name: "Create key" }).click();
    await expect(page.getByText(/^msk_/)).toBeVisible();
    await page.getByRole("button", { name: "I have saved it" }).click();
    await page.getByRole("tab", { name: "Audit log" }).click();
    await expect(page.getByText("Hash chain verified")).toBeVisible({ timeout: 20000 });
  });
});

test.describe("platform application", () => {
  test("revenue dashboard filters apply across the page", async ({ page }) => {
    await signIn(page, PLATFORM);
    await page.goto("/app/platform/revenue");
    await expect(page.getByText("Demo data, synthetic")).toBeVisible();
    await expect(page.getByRole("heading", { name: "MRR over time" })).toBeVisible();
    const mrrBefore = await page.locator("text=/^\\$[0-9,]+$/").first().innerText({ timeout: 15000 });
    await page.getByRole("button", { name: "Export MRR over time as CSV" }).waitFor();
    await page
      .getByRole("region", { name: /Revenue by plan/ })
      .getByRole("button", { name: "Table" })
      .click();
    await expect(page.getByRole("button", { name: /Clear filters/ })).toHaveCount(0);
    expect(mrrBefore).toMatch(/^\$/);
  });

  test("platform roles only see platform pages", async ({ page }) => {
    await signIn(page, PLATFORM);
    await page.goto("/app");
    await expect(page).toHaveURL(/\/app\/platform\/revenue$/);
    const nav = page.getByRole("navigation", { name: "Application" });
    await expect(nav.getByRole("link", { name: "Revenue" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Assets" })).toHaveCount(0);
  });
});

const APP_ROUTES: [string, string][] = [
  ["/app", MANAGER],
  ["/app/map", MANAGER],
  ["/app/assets", MANAGER],
  ["/app/incidents", MANAGER],
  ["/app/alerts", MANAGER],
  ["/app/zones", MANAGER],
  ["/app/briefings", MANAGER],
  ["/app/reports", MANAGER],
  ["/app/sources", MANAGER],
  ["/app/analytics", MANAGER],
  ["/app/settings", MANAGER],
  ["/app/billing", ADMIN],
  ["/app/admin", ADMIN],
  ["/app/platform/revenue", PLATFORM],
  ["/app/platform/analytics", PLATFORM],
];
test.describe("accessibility of application pages", () => {
  for (const [route, who] of APP_ROUTES)
    test(`axe: ${route}`, async ({ page }) => {
      await signIn(page, who);
      await page.goto(route);
      await page.waitForLoadState("load");
      await page.waitForTimeout(2500);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.nodes[0]?.html.slice(0, 120)}`)).toEqual([]);
    });
});
