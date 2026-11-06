"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const email = String(new FormData(e.currentTarget).get("email") ?? "").trim();
    setBusy(true);
    setError("");
    try {
      await api("/auth/password/forgot", { method: "POST", body: { email } });
      setSent(true);
    } catch {
      setError("The request could not be sent. Check the address and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Forgot your password"
      intro="Enter your email address and we will send a link to choose a new password if the account exists."
    >
      {sent ? (
        <div role="status" className="rounded-control bg-brand-100 p-4 text-slate-800">
          If the account exists, a reset message has been sent. The link works for 30 minutes.
        </div>
      ) : (
        <form method="post" onSubmit={submit} className="space-y-5" noValidate>
          <Field label="Email" htmlFor="email">
            <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
          </Field>
          {error ? (
            <p role="alert" className="text-small text-danger">
              {error}
            </p>
          ) : null}
          <Button type="submit" size="lg" className="w-full" disabled={busy}>
            {busy ? "Sending" : "Send reset link"}
          </Button>
        </form>
      )}
      <p className="mt-6 text-small">
        <Link href="/login" className="font-medium text-brand-600 underline">
          Back to log in
        </Link>
      </p>
    </AuthLayout>
  );
}
