"use client";

import * as NavigationMenu from "@radix-ui/react-navigation-menu";
import { ChevronDown, Menu } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Logo } from "@/components/art/logo";
import { Icon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogClose, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { industries, platformNav, solutions } from "@/content/site";
import { cn } from "@/lib/utils";

type MenuLink = { title: string; href: string; description: string; icon: string };
type Featured = { eyebrow: string; title: string; body: string; href: string; cta: string };

const solutionLinks: MenuLink[] = solutions.map((s) => ({
  title: s.title,
  href: `/solutions/${s.slug}`,
  description: s.summary,
  icon: s.icon,
}));
const industryLinks: MenuLink[] = industries.map((i) => ({
  title: i.title,
  href: `/industries/${i.slug}`,
  description: i.short,
  icon: "Layers",
}));

const featured: Record<string, Featured> = {
  platform: {
    eyebrow: "Method",
    title: "How place linking is measured",
    body: "Evaluation on public geoparsing corpora, including where the system fails.",
    href: "/methodology",
    cta: "Read the methodology",
  },
  solutions: {
    eyebrow: "Article",
    title: "Why place names break news geocoding",
    body: "The ambiguity problem in practice and what to do about it.",
    href: "/resources/why-place-names-break-news-geocoding",
    cta: "Read the article",
  },
  industries: {
    eyebrow: "Illustrative scenario",
    title: "See a worked scenario",
    body: "Each industry page walks through a labeled, illustrative scenario.",
    href: "/industries/logistics-shipping",
    cta: "View an example",
  },
};

function MegaPanel({ links, feature, cols = 2 }: { links: MenuLink[]; feature: Featured; cols?: 2 | 3 }) {
  return (
    <div
      className={cn(
        "grid w-[min(860px,92vw)] gap-6 p-6",
        cols === 3 ? "grid-cols-[1fr_1fr_260px]" : "grid-cols-[1fr_1fr_260px]",
      )}
    >
      <ul className="col-span-2 grid grid-cols-2 gap-1">
        {links.map((l) => (
          <li key={l.href}>
            <NavigationMenu.Link asChild>
              <Link href={l.href} className="flex gap-3 rounded-control p-3 hover:bg-slate-100">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
                  <Icon name={l.icon} className="size-5" />
                </span>
                <span>
                  <span className="block font-medium text-ink">{l.title}</span>
                  <span className="block text-small text-slate-600">{l.description}</span>
                </span>
              </Link>
            </NavigationMenu.Link>
          </li>
        ))}
      </ul>
      <div className="rounded-card bg-ink p-5 text-white">
        <p className="text-caption font-medium uppercase tracking-wider text-[#8FC2FF]">{feature.eyebrow}</p>
        <p className="mt-2 text-h4 font-semibold text-white">{feature.title}</p>
        <p className="mt-2 text-small text-slate-300">{feature.body}</p>
        <NavigationMenu.Link asChild>
          <Link
            href={feature.href}
            className="mt-4 inline-block text-small font-medium text-white underline underline-offset-4"
          >
            {feature.cta}
          </Link>
        </NavigationMenu.Link>
      </div>
    </div>
  );
}

const triggerClass =
  "group inline-flex h-10 items-center gap-1 rounded-control px-3 text-small font-medium text-slate-700 hover:bg-slate-100 hover:text-ink data-[state=open]:bg-slate-100";
const linkClass =
  "inline-flex h-10 items-center rounded-control px-3 text-small font-medium text-slate-700 hover:bg-slate-100 hover:text-ink";

export function Header() {
  const t = useTranslations("nav");
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const menus: { key: string; label: string; links: MenuLink[] }[] = [
    { key: "platform", label: t("platform"), links: platformNav },
    { key: "solutions", label: t("solutions"), links: solutionLinks },
    { key: "industries", label: t("industries"), links: industryLinks },
  ];

  return (
    <header
      className={cn(
        "sticky top-0 z-40 h-[72px] border-b transition-colors duration-200",
        scrolled ? "border-line bg-white/85 backdrop-blur-md" : "border-transparent bg-white",
      )}
    >
      <div className="container-page flex h-full items-center justify-between gap-6">
        <Link href="/" aria-label="Meridian Signal home" className="shrink-0">
          <Logo />
        </Link>

        <NavigationMenu.Root className="relative hidden xl:block" aria-label="Primary">
          <NavigationMenu.List className="flex items-center gap-1">
            {menus.map((m) => (
              <NavigationMenu.Item key={m.key}>
                <NavigationMenu.Trigger className={triggerClass}>
                  {m.label}
                  <ChevronDown
                    className="size-4 transition-transform duration-200 group-data-[state=open]:rotate-180"
                    aria-hidden="true"
                  />
                </NavigationMenu.Trigger>
                <NavigationMenu.Content className="absolute left-0 top-full">
                  <div className="mt-2 rounded-card border border-line bg-white shadow-e3">
                    <MegaPanel links={m.links} feature={featured[m.key] as Featured} />
                  </div>
                </NavigationMenu.Content>
              </NavigationMenu.Item>
            ))}
            <NavigationMenu.Item>
              <NavigationMenu.Link asChild>
                <Link href="/resources" className={linkClass}>
                  {t("resources")}
                </Link>
              </NavigationMenu.Link>
            </NavigationMenu.Item>
            <NavigationMenu.Item>
              <NavigationMenu.Link asChild>
                <Link href="/pricing" className={linkClass}>
                  {t("pricing")}
                </Link>
              </NavigationMenu.Link>
            </NavigationMenu.Item>
            <NavigationMenu.Item>
              <NavigationMenu.Link asChild>
                <Link href="/company" className={linkClass}>
                  {t("company")}
                </Link>
              </NavigationMenu.Link>
            </NavigationMenu.Item>
          </NavigationMenu.List>
        </NavigationMenu.Root>

        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="hidden h-10 items-center rounded-control px-3 text-small font-medium text-slate-700 hover:text-ink sm:inline-flex"
          >
            {t("login")}
          </Link>
          <Button asChild size="sm" className="hidden sm:inline-flex">
            <Link href="/contact">{t("demo")}</Link>
          </Button>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="sm" className="xl:hidden" aria-label={t("menu")}>
                <Menu className="size-5" aria-hidden="true" />
              </Button>
            </DialogTrigger>
            <DialogContent side="right" closeLabel={t("close")} aria-describedby={undefined}>
              <DialogTitle className="sr-only">{t("menu")}</DialogTitle>
              <nav aria-label="Mobile" className="mt-8 space-y-6">
                {menus.map((m) => (
                  <div key={m.key}>
                    <p className="mb-2 text-caption font-semibold uppercase tracking-wider text-slate-600">
                      {m.label}
                    </p>
                    <ul className="space-y-1">
                      {m.links.map((l) => (
                        <li key={l.href}>
                          <DialogClose asChild>
                            <Link
                              href={l.href}
                              className="block rounded-control px-2 py-2 text-ink hover:bg-slate-100"
                            >
                              {l.title}
                            </Link>
                          </DialogClose>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                <ul className="space-y-1 border-t border-line pt-4">
                  {[
                    ["/resources", t("resources")],
                    ["/pricing", t("pricing")],
                    ["/company", t("company")],
                    ["/login", t("login")],
                  ].map(([href, label]) => (
                    <li key={href}>
                      <DialogClose asChild>
                        <Link
                          href={href as string}
                          className="block rounded-control px-2 py-2 text-ink hover:bg-slate-100"
                        >
                          {label}
                        </Link>
                      </DialogClose>
                    </li>
                  ))}
                </ul>
                <DialogClose asChild>
                  <Button asChild className="w-full">
                    <Link href="/contact">{t("demo")}</Link>
                  </Button>
                </DialogClose>
              </nav>
            </DialogContent>
          </Dialog>
        </div>
      </div>
      <div className="absolute left-0 right-0 top-full flex justify-center" />
    </header>
  );
}
