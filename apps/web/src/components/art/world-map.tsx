import world from "@/content/world.json";
import { SeverityMarker } from "./severity-marker";

type View = { x: number; y: number; w: number; h: number };

/** Country outlines (Natural Earth) with recent located incidents from the demonstration database. */
export function WorldMap({
  view,
  className,
  markers = true,
  markerScale = 1,
  land = "#E3EAF4",
  stroke = "#FFFFFF",
  background = "transparent",
}: {
  view?: View;
  className?: string;
  markers?: boolean;
  markerScale?: number;
  land?: string;
  stroke?: string;
  background?: string;
}) {
  const box = view ?? { x: 0, y: 0, w: world.width, h: world.height };
  return (
    <svg
      viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
      className={className}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <rect x={box.x} y={box.y} width={box.w} height={box.h} fill={background} />
      <path d={world.d} fill={land} stroke={stroke} strokeWidth={0.5} strokeLinejoin="round" />
      {markers
        ? world.incidents
            .filter((p) => p.x >= box.x && p.x <= box.x + box.w && p.y >= box.y && p.y <= box.y + box.h)
            .map((p, i) => <SeverityMarker key={i} x={p.x} y={p.y} level={p.level} scale={markerScale} />)
        : null}
    </svg>
  );
}
