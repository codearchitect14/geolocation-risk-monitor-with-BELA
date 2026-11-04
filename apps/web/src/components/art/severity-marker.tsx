/** Map marker: shape and size change with level in addition to color. Level 1 circle, 2 square, 3 triangle, 4 diamond. */
export const SEVERITY_COLORS = ["", "#7AA6D8", "#E69F00", "#D55E5E", "#8E1B1B"] as const;

export function SeverityMarker({
  x,
  y,
  level,
  scale = 1,
}: {
  x: number;
  y: number;
  level: number;
  scale?: number;
}) {
  const l = Math.min(4, Math.max(1, level));
  const s = (3.2 + l * 0.9) * scale;
  const color = SEVERITY_COLORS[l];
  const common = { fill: color, stroke: "#FFFFFF", strokeWidth: 1 * scale };
  if (l === 1) return <circle cx={x} cy={y} r={s} {...common} />;
  if (l === 2) return <rect x={x - s} y={y - s} width={s * 2} height={s * 2} {...common} />;
  if (l === 3)
    return (
      <polygon
        points={`${x},${y - s * 1.2} ${x + s * 1.1},${y + s * 0.9} ${x - s * 1.1},${y + s * 0.9}`}
        {...common}
      />
    );
  return (
    <polygon
      points={`${x},${y - s * 1.3} ${x + s * 1.3},${y} ${x},${y + s * 1.3} ${x - s * 1.3},${y}`}
      {...common}
    />
  );
}
