"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { Logo } from "@/components/art/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { industries, platformNav, solutions } from "@/content/site";
import { api, ApiError } from "@/lib/api";

const columns: { title: string; links: [string, string][] }[] = [
  { title: "Platform", links: platformNav.map((p) => [p.title, p.href]) },
  { title: "Solutions", links: solutions.map((s) => [s.title, `/solutions/${s.slug}`]) },
  { title: "Industries", links: industries.map((i) => [i.title, `/industries/${i.slug}`]) },
  {
    title: "Resources",
    links: [
      ["Articles", "/resources"],
      ["Methodology", "/methodology"],
      ["Developers", "/developers"],
      ["Pricing", "/pricing"],
      ["Security", "/security"],
    ],
  },
  {
    title: "Company",
    links: [
      ["About", "/company"],
      ["Contact", "/contact"],
      ["Log in", "/login"],
    ],
  },
];

function Newsletter() {
  const t = useTranslations("footer");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("busy");
    try {
      await api("/newsletter/subscribe", { method: "POST", body: { email } });
      setState("done");
    } catch (err) {
      setMessage(
        err instanceof ApiError && err.status === 429
          ? err.message
          : "Enter a valid email address and try again.",
      );
      setState("error");
    }
  }

  return (
    <form onSubmit={submit} className="max-w-md" noValidate>
      <p className="font-medium text-white">{t("newsletter")}</p>
      <p className="mt-1 text-small text-slate-300">{t("newsletterHint")}</p>
      {state === "done" ? (
        <p role="status" className="mt-3 text-small text-[#8FE0C0]">
          {t("subscribed")}
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          <label htmlFor="newsletter-email" className="sr-only">
            {t("email")}
          </label>
          <Input
            id="newsletter-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("email")}
            className="border-white/20 bg-white/10 text-white placeholder:text-slate-300"
          />
          <Button type="submit" variant="inverse" disabled={state === "busy"}>
            {t("subscribe")}
          </Button>
        </div>
      )}
      {state === "error" ? (
        <p role="alert" className="mt-2 text-small text-[#FFB4AB]">
          {message}
        </p>
      ) : null}
    </form>
  );
}

export function Footer() {
  const t = useTranslations("footer");
  return (
    <footer className="bg-ink text-slate-300">
      <div className="container-page section-pad">
        <div className="grid gap-12 lg:grid-cols-[1fr_2fr]">
          <div className="space-y-6">
            <Logo tone="light" />
            <Newsletter />
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-8 sm:grid-cols-3 lg:grid-cols-5">
            {columns.map((c) => (
              <div key={c.title}>
                <p className="text-small font-semibold text-white">{c.title}</p>
                <ul className="mt-3 space-y-2">
                  {c.links.map(([label, href]) => (
                    <li key={href}>
                      <Link href={href} className="text-small hover:text-white">
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <div className="mt-12 space-y-3 border-t border-white/10 pt-8 text-small">
          <p>{t("disclaimer")}</p>
          <p className="text-slate-400">{t("credits")}</p>
          <div className="flex flex-wrap items-center justify-between gap-3 text-slate-400">
            <p>© 2026 Meridian Signal. {t("copyright")} Demonstration environment.</p>
            <ul className="flex gap-5">
              <li>
                <Link href="/legal/privacy" className="hover:text-white">
                  {t("privacy")}
                </Link>
              </li>
              <li>
                <Link href="/legal/terms" className="hover:text-white">
                  {t("terms")}
                </Link>
              </li>
              <li>
                <Link href="/legal/cookies" className="hover:text-white">
                  {t("cookies")}
                </Link>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </footer>
  );
}
