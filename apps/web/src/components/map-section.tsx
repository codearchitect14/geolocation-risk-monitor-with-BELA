"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { MapMarker } from "./map-view";

const MapView = dynamic(() => import("./map-view"), {
  ssr: false,
  loading: () => <div className="size-full animate-pulse bg-slate-100" aria-hidden="true" />,
});

/** Loads the map only when it approaches the viewport, then renders it with an accessible table of the same markers. */
export function MapSection({ markers, label }: { markers: MapMarker[]; label: string }) {
  const holder = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), {
      rootMargin: "300px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div>
      <div ref={holder} className="relative h-[420px] overflow-hidden rounded-card border border-line">
        {near ? (
          <MapView markers={markers} label={label} className="size-full" />
        ) : (
          <div className="size-full bg-slate-100" aria-hidden="true" />
        )}
      </div>
      <details className="mt-3 rounded-card border border-line bg-white p-4 text-small">
        <summary className="cursor-pointer font-medium text-ink">Show the same incidents as a table</summary>
        <table className="mt-3 w-full text-left">
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr className="border-b border-line text-slate-600">
              <th className="py-2 pr-4 font-medium">Incident</th>
              <th className="py-2 pr-4 font-medium">Level</th>
              <th className="py-2 font-medium">Position</th>
            </tr>
          </thead>
          <tbody>
            {markers.map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="py-2 pr-4">{m.label}</td>
                <td className="py-2 pr-4 tabular">Level {m.level}</td>
                <td className="py-2 tabular">
                  {m.lat.toFixed(1)}, {m.lon.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
