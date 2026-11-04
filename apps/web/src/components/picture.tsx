import manifest from "@/lib/image-manifest.json";

type Entry = { widths: number[]; ratio: number };
const entries = manifest as Record<string, Entry>;

/** Responsive AVIF and WebP with explicit dimensions, so the page does not shift while images load. */
export function Picture({
  name,
  alt,
  sizes = "(min-width: 1024px) 560px, 100vw",
  priority = false,
  className,
}: {
  name: string;
  alt: string;
  sizes?: string;
  priority?: boolean;
  className?: string;
}) {
  const entry = entries[name];
  if (!entry) return null;
  const largest = Math.max(...entry.widths);
  const set = (fmt: string) => entry.widths.map((w) => `/images/${name}-${w}.${fmt} ${w}w`).join(", ");
  return (
    <picture>
      <source type="image/avif" srcSet={set("avif")} sizes={sizes} />
      <source type="image/webp" srcSet={set("webp")} sizes={sizes} />
      <img
        src={`/images/${name}-${largest}.webp`}
        alt={alt}
        width={largest}
        height={Math.round(largest * entry.ratio)}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        fetchPriority={priority ? "high" : "auto"}
        className={className}
      />
    </picture>
  );
}
