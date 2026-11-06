"use client";

import { Command, LogOut, Menu, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Logo } from "@/components/art/logo";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { SessionProvider, useSession } from "@/lib/app/session";
import { cn } from "@/lib/utils";
import { CommandPalette } from "./command-palette";
import { ErrorBoundary } from "./error-boundary";
import { allowedPath, homeFor, NAV_GROUPS } from "./nav";
import { Notifications } from "./notifications";
import { ThemeContext, type Theme } from "./theme";

const IDLE_MINUTES = 30;

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const { me } = useSession();
  return (
    <nav aria-label="Application" className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      <Link href={homeFor(me.role)} className="px-2 py-1" aria-label="Meridian Signal home">
        <Logo />
      </Link>
      {NAV_GROUPS.map((g) => {
        const items = g.items.filter((i) => i.allow(me.role));
        if (!items.length) return null;
        return (
          <div key={g.label}>
            <div className="mb-1 px-2 text-caption font-medium uppercase tracking-wide text-slate-500">
              {g.label}
            </div>
            <ul className="space-y-0.5">
              {items.map((i) => {
                const active = i.href === "/app" ? pathname === "/app" : pathname.startsWith(i.href);
                return (
                  <li key={i.href}>
                    <Link
                      href={i.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2.5 rounded-control px-2.5 py-2 text-small",
                        active ? "bg-brand-100 font-medium text-ink" : "text-slate-700 hover:bg-slate-100",
                      )}
                    >
                      <i.icon className="size-4" aria-hidden="true" />
                      {i.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const { me } = useSession();
  const pathname = usePathname() ?? "/app";
  const router = useRouter();
  const [theme, setTheme] = useState<Theme>("light");
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);
  const [help, setHelp] = useState(false);
  const [idle, setIdle] = useState(false);
  const last = useRef(Date.now());

  useEffect(() => {
    try {
      const saved = localStorage.getItem("ms_theme");
      if (saved === "dark" || saved === "light") setTheme(saved);
      else if (window.matchMedia("(prefers-color-scheme: dark)").matches) setTheme("dark");
    } catch {
      /* storage can be unavailable */
    }
  }, []);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("ms_theme", next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  }, []);

  // Route guard: a role that may not open this page is sent to its own home.
  useEffect(() => {
    if (!allowedPath(pathname, me.role)) router.replace(homeFor(me.role));
  }, [pathname, me.role, router]);

  // Idle timeout: after 30 minutes without input the session is ended; a warning shows first.
  useEffect(() => {
    const touch = () => (last.current = Date.now());
    const events = ["pointerdown", "keydown", "scroll"] as const;
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const timer = window.setInterval(() => {
      const idleMs = Date.now() - last.current;
      if (idleMs > IDLE_MINUTES * 60_000) void signOut();
      else setIdle(idleMs > (IDLE_MINUTES - 2) * 60_000);
    }, 15_000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, touch));
      window.clearInterval(timer);
    };
  }, [signOut]);

  // Keyboard shortcuts: Ctrl/Cmd+K, "?" for help, "g" then a letter to go to a page.
  useEffect(() => {
    let goMode = false;
    let timer = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        return setPalette((p) => !p);
      }
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.ctrlKey || e.metaKey || e.altKey)
        return;
      if (e.key === "?") return setHelp(true);
      if (goMode) {
        goMode = false;
        const item = NAV_GROUPS.flatMap((g) => g.items).find((i) => i.key === e.key && i.allow(me.role));
        if (item) router.push(item.href);
        return;
      }
      if (e.key === "g") {
        goMode = true;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => (goMode = false), 1500);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [me.role, router]);

  const tenantUser = !(me.role === "platform_admin" || me.role === "finance_analyst");
  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      <div className="app-root min-h-dvh bg-page" data-theme={theme}>
        <a
          href="#app-main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[70] focus:rounded-control focus:bg-white focus:p-3"
        >
          Skip to content
        </a>
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-white lg:block">
          <Sidebar />
        </aside>
        <div className="lg:pl-60">
          <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line bg-white/95 px-4 backdrop-blur">
            <button
              type="button"
              className="rounded-control p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
              aria-label="Open navigation"
              onClick={() => setMenu(true)}
            >
              <Menu className="size-5" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setPalette(true)}
              className="flex h-9 w-full max-w-md items-center gap-2 rounded-control border border-line bg-slate-50 px-3 text-small text-slate-600 hover:border-brand-500"
            >
              <Command className="size-4" aria-hidden="true" /> Search assets, incidents, places
              <kbd className="ml-auto hidden rounded border border-line px-1.5 text-caption sm:inline">
                Ctrl K
              </kbd>
            </button>
            <div className="ml-auto flex items-center gap-1">
              {tenantUser ? <Notifications /> : null}
              <button
                type="button"
                onClick={toggle}
                className="rounded-control p-2 text-slate-700 hover:bg-slate-100"
                aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              >
                {theme === "dark" ? (
                  <Sun className="size-5" aria-hidden="true" />
                ) : (
                  <Moon className="size-5" aria-hidden="true" />
                )}
              </button>
              <div className="ml-2 hidden text-right leading-tight sm:block">
                <div className="text-small font-medium text-ink">{me.display_name}</div>
                <div className="text-caption text-slate-600">{me.role.replace(/_/g, " ")}</div>
              </div>
              <Button size="sm" variant="ghost" onClick={signOut} aria-label="Sign out">
                <LogOut className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </header>
          <main id="app-main" tabIndex={-1} className="mx-auto max-w-[1400px] p-4 focus:outline-none sm:p-6">
            <ErrorBoundary key={pathname}>{children}</ErrorBoundary>
          </main>
        </div>

        <Dialog open={menu} onOpenChange={setMenu}>
          <DialogContent side="left" className="p-0">
            <DialogTitle className="sr-only">Navigation</DialogTitle>
            <DialogDescription className="sr-only">Application pages</DialogDescription>
            <Sidebar onNavigate={() => setMenu(false)} />
          </DialogContent>
        </Dialog>
        <CommandPalette open={palette} onOpenChange={setPalette} />
        <Dialog open={help} onOpenChange={setHelp}>
          <DialogContent>
            <DialogTitle className="text-h4 text-ink">Keyboard shortcuts</DialogTitle>
            <DialogDescription className="text-small text-slate-600">
              Available on every page.
            </DialogDescription>
            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-small">
              <dt className="font-mono">Ctrl K</dt>
              <dd>Search</dd>
              <dt className="font-mono">?</dt>
              <dd>This list</dd>
              <dt className="font-mono">g then o, m, i, a, s, z</dt>
              <dd>Go to overview, map, incidents, alerts, assets, zones</dd>
              <dt className="font-mono">j / k, a, d</dt>
              <dd>Alerts: next or previous, acknowledge, dismiss</dd>
            </dl>
          </DialogContent>
        </Dialog>
        <Dialog open={idle} onOpenChange={(o) => !o && ((last.current = Date.now()), setIdle(false))}>
          <DialogContent>
            <DialogTitle className="text-h4 text-ink">Still there?</DialogTitle>
            <DialogDescription className="text-small text-slate-600">
              For your security you will be signed out soon because of inactivity.
            </DialogDescription>
            <Button className="mt-4" onClick={() => ((last.current = Date.now()), setIdle(false))}>
              Stay signed in
            </Button>
          </DialogContent>
        </Dialog>
      </div>
    </ThemeContext.Provider>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <Frame>{children}</Frame>
    </SessionProvider>
  );
}
