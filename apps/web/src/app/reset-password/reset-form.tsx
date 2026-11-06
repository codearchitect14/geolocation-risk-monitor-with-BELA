"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, ApiError } from "@/lib/api";

export function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const password = String(data.get("password") ?? "");
    if (password !== String(data.get("confirm") ?? "")) return setError("The two passwords do not match.");
    setBusy(true);
    setError("");
    try {
      await api("/auth/password/reset", { method: "POST", body: { token, new_password: password } });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError && (err.status === 422 || err.status === 400)
          ? err.message
          : "The password could not be changed. Request a new link and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!token)
    return (
      <p role="alert" className="text-danger">
        This link is missing its token.{" "}
        <Link href="/forgot-password" className="underline">
          Request a new link
        </Link>
        .
      </p>
    );
  if (done)
    return (
      <div role="status" className="rounded-control bg-brand-100 p-4">
        The password was changed.{" "}
        <Link href="/login" className="font-medium text-brand-600 underline">
          Log in with the new password
        </Link>
        .
      </div>
    );
  return (
    <form method="post" onSubmit={submit} className="space-y-5" noValidate>
      <Field
        label="New password"
        htmlFor="password"
        hint="At least 12 characters. Avoid your name or email address."
      >
        <Input id="password" name="password" type="password" autoComplete="new-password" required autoFocus />
      </Field>
      <Field label="Confirm new password" htmlFor="confirm">
        <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
      </Field>
      {error ? (
        <p role="alert" className="text-small text-danger">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" disabled={busy}>
        {busy ? "Saving" : "Change password"}
      </Button>
    </form>
  );
}
