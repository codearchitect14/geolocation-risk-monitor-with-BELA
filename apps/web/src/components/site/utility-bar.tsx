"use client";

import { Globe } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { LOCALES, useLocale, type Locale } from "@/lib/i18n";

export function UtilityBar() {
  const t = useTranslations("utility");
  const { locale, setLocale } = useLocale();
  return (
    <div className="hidden h-10 border-b border-white/10 bg-ink text-small text-slate-300 md:block">
      <div className="container-page flex h-full items-center justify-between">
        <p className="text-caption">Operational disruption intelligence</p>
        <div className="flex items-center gap-5">
          <Link href="/contact?topic=support" className="hover:text-white">
            {t("support")}
          </Link>
          <Link href="/methodology#feeds" className="hover:text-white">
            {t("status")}
          </Link>
          <Link href="/developers" className="hover:text-white">
            {t("developers")}
          </Link>
          <label className="flex items-center gap-1.5">
            <Globe className="size-4" aria-hidden="true" />
            <span className="sr-only">{t("language")}</span>
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="cursor-pointer rounded border-0 bg-transparent py-0.5 pr-1 text-small text-slate-300 hover:text-white"
            >
              {LOCALES.map((l) => (
                <option key={l.code} value={l.code} className="text-ink">
                  {l.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </div>
  );
}
