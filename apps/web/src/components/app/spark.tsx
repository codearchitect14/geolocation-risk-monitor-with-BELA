/** Small inline trend line. Decorative: the value and change next to it carry the information. */
export function Spark({ values, color = "#2F74D8" }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${22 - ((v - min) / span) * 20}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 24" className="mt-1 h-6 w-full" aria-hidden="true" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
