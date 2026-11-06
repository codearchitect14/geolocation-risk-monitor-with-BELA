import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";

export const PASSWORD = process.env.E2E_PASSWORD ?? "web-e2e passphrase 2026!";
const STORE = path.resolve(process.cwd(), "../../.local/dev_mfa.json");

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of input.replace(/=+$/, "").toUpperCase())
    bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  return Buffer.from((bits.match(/.{8}/g) ?? []).map((b) => parseInt(b, 2)));
}

/** RFC 6238 code for the 30 second step that is `stepOffset` steps from now. */
export function totp(secret: string, stepOffset = 0): string {
  const counter = Math.floor(Date.now() / 30000) + stepOffset;
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", base32Decode(secret)).update(buf).digest();
  const o = (h[h.length - 1] as number) & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

type Cookie = Awaited<ReturnType<ReturnType<Page["context"]>["cookies"]>>;
/** Sessions are reused within a run: a one-time code cannot be used twice in the same 30 second step. */
const SESSIONS = path.resolve(process.cwd(), "../../.local/e2e-sessions.json");
type Saved = Record<string, { at: number; cookies: Cookie }>;
const loadSessions = (): Saved =>
  fs.existsSync(SESSIONS) ? (JSON.parse(fs.readFileSync(SESSIONS, "utf8")) as Saved) : {};

const secrets = (): Record<string, string> =>
  fs.existsSync(STORE) ? JSON.parse(fs.readFileSync(STORE, "utf8")) : {};

/** Sign in through the API so the browser context holds the session cookies; handles authenticator enrollment. */
export async function signIn(page: Page, email: string): Promise<void> {
  const cached = loadSessions()[email];
  if (cached && Date.now() - cached.at < 10 * 60_000) return page.context().addCookies(cached.cookies);
  await freshSignIn(page, email);
  fs.mkdirSync(path.dirname(SESSIONS), { recursive: true });
  fs.writeFileSync(
    SESSIONS,
    JSON.stringify({
      ...loadSessions(),
      [email]: { at: Date.now(), cookies: await page.context().cookies() },
    }),
  );
}

async function freshSignIn(page: Page, email: string): Promise<void> {
  const api = page.context().request;
  const csrf = async () => (await page.context().cookies()).find((c) => c.name === "ms_csrf")?.value ?? "";
  const post = async (url: string, data: unknown) => {
    const res = await api.post(`/api/v1${url}`, { data, headers: { "X-CSRF-Token": await csrf() } });
    if (!res.ok()) throw new Error(`${url} failed: ${res.status()} ${await res.text()}`);
    return (await res.json()) as Record<string, string>;
  };
  const login = await post("/auth/login", { email, password: PASSWORD });
  if (login.status === "mfa_enrollment_required") {
    const setup = await post("/auth/mfa/setup", { setup_token: login.setup_token });
    fs.mkdirSync(path.dirname(STORE), { recursive: true });
    fs.writeFileSync(STORE, JSON.stringify({ ...secrets(), [email]: setup.secret }));
    await post("/auth/mfa/verify", { setup_token: login.setup_token, code: totp(setup.secret as string) });
  } else if (login.status === "mfa_required") {
    const secret = secrets()[email];
    if (!secret) throw new Error(`no authenticator secret stored for ${email}`);
    let last: unknown;
    for (const offset of [0, 1, -1]) {
      try {
        return void (await post("/auth/mfa/verify", {
          mfa_token: login.mfa_token,
          code: totp(secret, offset),
        }));
      } catch (e) {
        last = e;
      }
    }
    throw last;
  }
}
