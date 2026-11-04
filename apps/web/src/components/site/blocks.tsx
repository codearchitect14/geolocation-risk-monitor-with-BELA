import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Section({
  children,
  className,
  tone = "page",
  id,
  label,
}: {
  children: ReactNode;
  className?: string;
  tone?: "page" | "white" | "ink";
  id?: string;
  label?: string;
}) {
  return (
    <section
      id={id}
      aria-label={label}
      className={cn(
        "section-pad",
        tone === "white" && "bg-white",
        tone === "ink" && "bg-ink text-slate-200",
        className,
      )}
    >
      <div className="container-page">
        <div className="content-width">{children}</div>
      </div>
    </section>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  children,
  tone = "light",
  align = "left",
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  tone?: "light" | "dark";
  align?: "left" | "center";
}) {
  return (
    <div className={cn("mb-10 max-w-3xl", align === "center" && "mx-auto text-center")}>
      {eyebrow ? (
        <p
          className={cn(
            "mb-3 text-small font-semibold uppercase tracking-wider",
            tone === "dark" ? "text-[#8FC2FF]" : "text-teal-700",
          )}
        >
          {eyebrow}
        </p>
      ) : null}
      <h2 className={cn("text-h2", tone === "dark" && "!text-white")}>{title}</h2>
      {children ? (
        <p className={cn("mt-4 text-body", tone === "dark" ? "text-slate-300" : "text-slate-700")}>
          {children}
        </p>
      ) : null}
    </div>
  );
}

export function PageHero({
  eyebrow,
  title,
  children,
  actions,
  aside,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="border-b border-line bg-white">
      <div className="container-page">
        <div className="content-width grid items-center gap-10 py-14 lg:grid-cols-[1.1fr_0.9fr] lg:py-20">
          <div>
            {eyebrow ? (
              <p className="mb-3 text-small font-semibold uppercase tracking-wider text-teal-700">
                {eyebrow}
              </p>
            ) : null}
            <h1 className="text-[2.25rem] leading-[2.75rem] lg:text-h1 lg:leading-[3.125rem]">{title}</h1>
            {children ? (
              <div className="mt-5 max-w-2xl text-[1.125rem] leading-8 text-slate-700">{children}</div>
            ) : null}
            {actions ? <div className="mt-8 flex flex-wrap gap-3">{actions}</div> : null}
          </div>
          {aside ? <div>{aside}</div> : null}
        </div>
      </div>
    </section>
  );
}

export function CtaBand({
  title = "See it with your own sites",
  body = "Tell us about your network and we will show how reports near your locations would appear.",
}: {
  title?: string;
  body?: string;
}) {
  return (
    <section className="bg-ink" aria-label="Request a demo">
      <div className="container-page">
        <div className="content-width section-pad grid items-center gap-8 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <h2 className="text-h2 !text-white">{title}</h2>
            <p className="mt-3 max-w-xl text-slate-300">{body}</p>
          </div>
          <form action="/contact" method="get" className="flex flex-col gap-3 sm:flex-row">
            <label htmlFor="cta-email" className="sr-only">
              Work email
            </label>
            <input
              id="cta-email"
              name="email"
              type="email"
              required
              autoComplete="email"
              placeholder="Work email"
              className="h-12 flex-1 rounded-control border border-white/20 bg-white/10 px-4 text-white placeholder:text-slate-300"
            />
            <Button type="submit" variant="inverse" size="lg">
              Request a demo
            </Button>
          </form>
        </div>
      </div>
    </section>
  );
}

export function DemoActions() {
  return (
    <>
      <Button asChild size="lg">
        <Link href="/contact">Request a demo</Link>
      </Button>
      <Button asChild variant="secondary" size="lg">
        <Link href="/login">Log in to the platform</Link>
      </Button>
    </>
  );
}

export function Footnote({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-caption text-slate-600">{children}</p>;
}
