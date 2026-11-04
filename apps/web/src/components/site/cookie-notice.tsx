"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const KEY = "ms_notice_ack";

/** The site sets no analytics or advertising cookies, so this is an information notice with one action. */
export function CookieNotice() {
  const t = useTranslations("cookie");
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      setVisible(window.localStorage.getItem(KEY) !== "1");
    } catch {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;
  return (
    <section
      aria-label="Cookie notice"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-3xl rounded-card border border-line bg-white p-4 shadow-e3 sm:flex sm:items-center sm:gap-4"
    >
      <p className="text-small text-slate-700">
        {t("text")}{" "}
        <Link href="/legal/cookies" className="font-medium text-brand-600 underline underline-offset-2">
          {t("learn")}
        </Link>
      </p>
      <Button
        size="sm"
        className="mt-3 shrink-0 sm:mt-0"
        onClick={() => {
          try {
            window.localStorage.setItem(KEY, "1");
          } catch {
            /* ignore */
          }
          setVisible(false);
        }}
      >
        {t("ok")}
      </Button>
    </section>
  );
}
