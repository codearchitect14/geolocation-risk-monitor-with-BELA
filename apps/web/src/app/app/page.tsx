"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Me = { display_name?: string; email?: string; role?: string };

/** The product application arrives in the next phase. This page confirms that sign-in worked and allows sign-out. */
export default function AppLanding() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    api<Me>("/auth/me").then(setMe, () => setMe(null));
  }, []);
  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  }
  return (
    <div className="mx-auto max-w-xl px-6 py-24">
      <h1 className="text-h2">
        {me === undefined
          ? "Checking your session"
          : me
            ? `Signed in as ${me.display_name ?? me.email}`
            : "You are not signed in"}
      </h1>
      <p className="mt-4 text-slate-700">
        The product application is built in the next project phase. Your session is active and the application
        will open here.
      </p>
      <div className="mt-8 flex gap-3">
        {me ? (
          <Button variant="secondary" onClick={signOut}>
            Sign out
          </Button>
        ) : (
          <Button asChild>
            <Link href="/login">Log in</Link>
          </Button>
        )}
        <Button asChild variant="ghost">
          <Link href="/">Back to the website</Link>
        </Button>
      </div>
    </div>
  );
}
