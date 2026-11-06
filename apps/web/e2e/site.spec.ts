import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { ROUTES } from "./routes.mjs";

const PASSWORD = process.env.E2E_PASSWORD ?? "web-e2e passphrase 2026!";

test("home page content and primary actions", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Know what is happening near your operations, as it is reported.",
  );
  await expect(page.getByRole("link", { name: "Log in" }).first()).toHaveAttribute("href", "/login");
  await expect(page.getByRole("link", { name: "Request a demo" }).first()).toHaveAttribute(
    "href",
    "/contact",
  );
});

test("skip link moves focus to main content", async ({ page, browserName }) => {
  await page.goto("/pricing");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  if (browserName === "webkit") {
    // Safari does not move focus to links with Tab unless the user enables it (Option+Tab otherwise), so focus the link directly.
    await skip.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});

test("mega menu opens and closes from the keyboard", async ({ page }) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Platform" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: /Place linking/ })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(header.getByRole("link", { name: /Ingestion/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(header.getByRole("link", { name: /Place linking/ })).toBeHidden();
});

test("language selector translates the shared interface", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Language").selectOption("de");
  await expect(page.getByRole("link", { name: "Anmelden" }).first()).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
});

test("demo request validates and submits", async ({ page }) => {
  await page.goto("/contact");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Enter your name.")).toBeVisible();
  await page.getByLabel("Name").fill("Casey Morgan");
  await page.getByLabel("Work email").fill(`casey.${Date.now()}@example.org`);
  await page.getByLabel("Organization").fill("Example Freight");
  await page.getByLabel("Role").fill("Operations lead");
  await page.getByLabel("Industry").selectOption("Logistics and shipping");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("heading", { name: "Thank you" })).toBeVisible();
});

test("newsletter sign-up asks for confirmation", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email address").fill(`reader.${Date.now()}@example.org`);
  await page.getByRole("button", { name: "Subscribe" }).click();
  await expect(page.getByText("Check your inbox")).toBeVisible();
});

test("sign-in: wrong password gives a generic message, correct password reaches /app", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("e2e.analyst@example.org");
  await page.getByLabel("Password").fill("not the password at all");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.locator("p[role=alert]")).toHaveText("The email or password is not correct.");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("navigation", { name: "Application" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("forgot password gives the same answer for any address", async ({ page }) => {
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(`nobody.${Date.now()}@example.org`);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText("If the account exists, a reset message has been sent.")).toBeVisible();
});

test("no console errors or blocked resources on key pages", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(String(e)));
  for (const path of ["/", "/platform", "/methodology", "/resources", "/contact"]) {
    await page.goto(path);
    await page.waitForLoadState("load");
    await page.waitForTimeout(400);
    if (path === "/platform") {
      await page.getByRole("heading", { name: /Recent hazard records/ }).scrollIntoViewIfNeeded();
      await page.getByRole("region", { name: "Recent hazard records" }).waitFor();
      await page.waitForTimeout(1500);
    }
  }
  expect(problems).toEqual([]);
});

test("security headers are present", async ({ request }) => {
  const res = await request.get("/");
  const h = res.headers();
  expect(h["content-security-policy"]).toContain("default-src 'self'");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-powered-by"]).toBeUndefined();
});

for (const path of ROUTES) {
  test(`axe: ${path}`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("load");
    await page.waitForTimeout(400);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      results.violations.map(
        (v) =>
          `${v.id}: ${v.nodes
            .map((n) => n.target.join(" "))
            .slice(0, 3)
            .join(" | ")}`,
      ),
    ).toEqual([]);
  });
}
