"use client";

import { NextIntlClientProvider } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import en from "../../messages/en.json";
import es from "../../messages/es.json";
import fr from "../../messages/fr.json";
import de from "../../messages/de.json";

export const LOCALES = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
] as const;
export type Locale = (typeof LOCALES)[number]["code"];

const catalogs: Record<Locale, typeof en> = { en, es, fr, de };
const STORAGE_KEY = "ms_locale";

const LocaleContext = createContext<{ locale: Locale; setLocale: (l: Locale) => void }>({
  locale: "en",
  setLocale: () => undefined,
});

export const useLocale = () => useContext(LocaleContext);

/**
 * Interface strings (navigation, footer, notices) are translated. Page copy is English only; every page renders
 * statically in English and the shared chrome switches language after load, so the choice never makes a page dynamic.
 */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY) as Locale | null;
      if (stored && stored in catalogs) setLocaleState(stored);
    } catch {
      /* storage can be unavailable; English stays */
    }
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    document.documentElement.lang = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider locale={locale} messages={catalogs[locale]} timeZone="UTC">
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}
