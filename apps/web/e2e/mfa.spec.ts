import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import path from "node:path";
import { expect, test } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "web-e2e passphrase 2026!";
const API_DIR = path.resolve(process.cwd(), "../api");
const PYTHON = path.resolve(process.cwd(), "../../.venv/bin/python");

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of input.replace(/=+$/, "").toUpperCase())
    bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((b) => parseInt(b, 2)));
}

/** RFC 6238 code for the 30 second step that is `stepOffset` steps from now. */
function totp(secret: string, stepOffset = 0): string {
  const counter = Math.floor(Date.now() / 30000) + stepOffset;
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", base32Decode(secret)).update(buf).digest();
  const o = (h[h.length - 1] as number) & 0xf;
  const n = (h.readUInt32BE(o) & 0x7fffffff) % 1_000_000;
  return String(n).padStart(6, "0");
}

test("administrator enrolls an authenticator, saves recovery codes, then signs in with a code", async ({
  page,
}) => {
  const email = `e2e.admin.${Date.now()}@example.org`;
  execFileSync(
    PYTHON,
    [
      "-W",
      "ignore",
      "-m",
      "meridian.api.cli",
      "create-user",
      "--email",
      email,
      "--name",
      "E2E Admin",
      "--role",
      "tenant_admin",
      "--tenant",
      "web-e2e",
    ],
    {
      cwd: API_DIR,
      env: { ...process.env, PYTHONPATH: ".", MS_NEW_PASSWORD: PASSWORD },
      stdio: "ignore",
    },
  );

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByRole("heading", { name: "Set up your authenticator" })).toBeVisible();
  const secret = (await page.locator("code.font-mono").innerText()).trim();
  await page.getByLabel("Authentication code").fill(totp(secret));
  await page.getByRole("button", { name: "Verify and continue" }).click();

  await expect(page.getByRole("heading", { name: "Save your recovery codes" })).toBeVisible();
  expect(await page.locator("ul.font-mono li").count()).toBeGreaterThanOrEqual(8);
  await page.getByRole("button", { name: "I have saved the codes" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("navigation", { name: "Application" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByLabel("Authentication code")).toBeVisible();
  await page.getByLabel("Authentication code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.locator("p[role=alert]")).toHaveText("The code is not correct.");
  await page.getByLabel("Authentication code").fill(totp(secret, 1));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/app$/);
});
