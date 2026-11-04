"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, ApiError } from "@/lib/api";

type Step =
  | { name: "credentials" }
  | { name: "mfa"; token: string }
  | { name: "enroll"; token: string; secret: string; qr: string }
  | { name: "recovery"; codes: string[] };

type LoginResponse = {
  status: "ok" | "mfa_required" | "mfa_enrollment_required";
  mfa_token?: string;
  setup_token?: string;
};

function message(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429)
      return e.retryAfter
        ? `Too many attempts. Try again in ${Math.ceil(e.retryAfter / 60)} minutes.`
        : "Too many attempts. Try again later.";
    if (e.status === 401 || e.status === 403) return e.message;
  }
  return "Sign-in could not be completed. Try again.";
}

export function LoginFlow() {
  const router = useRouter();
  const [step, setStep] = useState<Step>({ name: "credentials" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [useRecovery, setUseRecovery] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  function field(form: HTMLFormElement, name: string): string {
    return String(new FormData(form).get(name) ?? "").trim();
  }

  const onCredentials = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const email = field(form, "email");
    const password = String(new FormData(form).get("password") ?? "");
    void run(async () => {
      const res = await api<LoginResponse>("/auth/login", { method: "POST", body: { email, password } });
      if (res.status === "ok") return void router.push("/app");
      if (res.status === "mfa_required" && res.mfa_token)
        return void setStep({ name: "mfa", token: res.mfa_token });
      if (res.status === "mfa_enrollment_required" && res.setup_token) {
        const setup = await api<{ secret: string; qr_svg: string }>("/auth/mfa/setup", {
          method: "POST",
          body: { setup_token: res.setup_token },
        });
        setStep({
          name: "enroll",
          token: res.setup_token,
          secret: setup.secret,
          qr: `data:image/svg+xml;utf8,${encodeURIComponent(setup.qr_svg)}`,
        });
      }
    });
  };

  const onMfa = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (step.name !== "mfa" && step.name !== "enroll") return;
    const form = e.currentTarget;
    const value = field(form, "code").replace(/\s+/g, "");
    const token = step.token;
    const enrolling = step.name === "enroll";
    void run(async () => {
      const body = enrolling
        ? { setup_token: token, code: value }
        : { mfa_token: token, ...(useRecovery ? { recovery_code: value } : { code: value }) };
      const res = await api<{ recovery_codes?: string[] }>("/auth/mfa/verify", { method: "POST", body });
      if (res.recovery_codes?.length) return void setStep({ name: "recovery", codes: res.recovery_codes });
      router.push("/app");
    });
  };

  if (step.name === "recovery") {
    return (
      <div>
        <h2 className="text-h4">Save your recovery codes</h2>
        <p className="mt-2 text-slate-700">
          Each code can be used once if you lose access to your authenticator. They are shown only now.
        </p>
        <ul className="mt-4 grid grid-cols-2 gap-2 rounded-control bg-slate-100 p-4 font-mono text-small">
          {step.codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <Button className="mt-6 w-full" size="lg" onClick={() => router.push("/app")}>
          I have saved the codes
        </Button>
      </div>
    );
  }

  if (step.name === "mfa" || step.name === "enroll") {
    return (
      <form onSubmit={onMfa} noValidate>
        {step.name === "enroll" ? (
          <div className="mb-6">
            <h2 className="text-h4">Set up your authenticator</h2>
            <p className="mt-2 text-slate-700">
              Administrator roles require a second factor. Scan the code with an authenticator app, then enter
              the six-digit code it shows.
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={step.qr}
              alt="QR code for the authenticator app"
              width={176}
              height={176}
              className="mt-4 rounded-control border border-line"
            />
            <p className="mt-3 text-caption text-slate-600">
              Cannot scan? Enter this key manually: <code className="font-mono">{step.secret}</code>
            </p>
          </div>
        ) : (
          <p className="mb-4 text-slate-700">
            Enter the {useRecovery ? "recovery code" : "six-digit code from your authenticator app"}.
          </p>
        )}
        <Field label={useRecovery ? "Recovery code" : "Authentication code"} htmlFor="code">
          <Input
            id="code"
            name="code"
            inputMode={useRecovery ? "text" : "numeric"}
            autoComplete="one-time-code"
            required
            autoFocus
          />
        </Field>
        {error ? (
          <p role="alert" className="mt-3 text-small text-danger">
            {error}
          </p>
        ) : null}
        <Button type="submit" size="lg" className="mt-6 w-full" disabled={busy}>
          {busy ? "Checking" : step.name === "enroll" ? "Verify and continue" : "Verify"}
        </Button>
        {step.name === "mfa" ? (
          <button
            type="button"
            onClick={() => setUseRecovery((v) => !v)}
            className="mt-4 text-small font-medium text-brand-600 underline"
          >
            {useRecovery ? "Use an authenticator code" : "Use a recovery code"}
          </button>
        ) : null}
      </form>
    );
  }

  return (
    <form onSubmit={onCredentials} noValidate className="space-y-5">
      <Field label="Email" htmlFor="email">
        <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
      </Field>
      <Field label="Password" htmlFor="password">
        <Input id="password" name="password" type="password" autoComplete="current-password" required />
      </Field>
      {error ? (
        <p role="alert" className="text-small text-danger">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" disabled={busy}>
        {busy ? "Signing in" : "Log in"}
      </Button>
      <p className="text-small">
        <Link href="/forgot-password" className="font-medium text-brand-600 underline">
          Forgot your password?
        </Link>
      </p>
    </form>
  );
}
