"use client";

import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LocaleProvider } from "@/lib/i18n";
import { ToastProvider } from "@/components/ui/toast";
import { CookieNotice } from "./cookie-notice";
import { Footer } from "./footer";
import { Header } from "./header";
import { UtilityBar } from "./utility-bar";

function SkipLink() {
  const t = useTranslations("common");
  return (
    <a
      href="#main"
      className="sr-only z-[70] rounded-control bg-white px-4 py-2 font-medium text-ink shadow-e3 focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
    >
      {t("skip")}
    </a>
  );
}

const BARE = ["/login", "/forgot-password", "/reset-password", "/app"];

export function SiteShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const chrome = !BARE.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  return (
    <LocaleProvider>
      <ToastProvider>
        <SkipLink />
        {chrome ? <UtilityBar /> : null}
        {chrome ? <Header /> : null}
        <main id="main" tabIndex={-1} className="focus:outline-none">
          {children}
        </main>
        {chrome ? <Footer /> : null}
        <CookieNotice />
      </ToastProvider>
    </LocaleProvider>
  );
}
