"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/art/logo";
import { WorldMap } from "@/components/art/world-map";

const STATEMENTS = [
  "Every location comes with a level and an uncertainty radius.",
  "Unresolved place names stay unresolved. They are never guessed onto the map.",
  "Your site locations stay inside your tenant.",
];

function Rotating() {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setI((n) => (n + 1) % STATEMENTS.length), 6000);
    return () => window.clearInterval(id);
  }, [paused]);
  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <p aria-live={paused ? "polite" : "off"} className="min-h-[5.5rem] text-h3 font-semibold text-white">
        {STATEMENTS[i]}
      </p>
      <div className="mt-6 flex gap-2" role="group" aria-label="Choose a statement">
        {STATEMENTS.map((s, n) => (
          <button
            key={s}
            type="button"
            aria-label={`Statement ${n + 1} of ${STATEMENTS.length}`}
            aria-current={n === i}
            onClick={() => setI(n)}
            className="flex h-6 min-w-6 items-center justify-center"
          >
            <span
              className={`block h-2 rounded-full transition-all ${n === i ? "w-8 bg-white" : "w-2 bg-white/40"}`}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

export function AuthLayout({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col px-6 py-8 sm:px-12 lg:px-16">
        <Link href="/" aria-label="Meridian Signal home">
          <Logo />
        </Link>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12">
          <h1 className="text-h2">{title}</h1>
          {intro ? <p className="mt-2 text-slate-700">{intro}</p> : null}
          <div className="mt-8">{children}</div>
          <p className="mt-10 rounded-control border border-dashed border-slate-400 bg-white p-3 text-caption text-slate-700">
            Demo data: this environment holds synthetic and illustrative data only.
          </p>
        </div>
        <p className="text-caption text-slate-600">
          Signals are situational awareness and not official warnings. Follow local authorities.
        </p>
      </div>
      <aside
        className="relative hidden overflow-hidden bg-ink lg:flex lg:flex-col lg:justify-end lg:p-16"
        aria-label="About the platform"
      >
        <WorldMap
          className="absolute inset-0 size-full opacity-30"
          land="#1B3F73"
          stroke="#0B1B33"
          markers={false}
        />
        <div className="relative max-w-md">
          <Rotating />
        </div>
      </aside>
    </div>
  );
}
