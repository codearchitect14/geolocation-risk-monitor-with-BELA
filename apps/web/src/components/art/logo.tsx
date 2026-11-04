import { BRAND } from "@/lib/utils";

/** In-house wordmark: a meridian line crossing a signal ring, then the name. */
export function Logo({ className, tone = "dark" }: { className?: string; tone?: "dark" | "light" }) {
  const text = tone === "dark" ? "#0B1B33" : "#FFFFFF";
  return (
    <svg
      className={className}
      height="28"
      viewBox="0 0 190 28"
      role="img"
      aria-label={BRAND}
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle cx="14" cy="14" r="12" fill="none" stroke="#1F5FBF" strokeWidth="2.5" />
      <ellipse cx="14" cy="14" rx="5" ry="12" fill="none" stroke="#00A3A3" strokeWidth="2" />
      <circle cx="14" cy="14" r="2.6" fill="#1F5FBF" />
      <text
        x="36"
        y="19.5"
        fontFamily="Inter Variable, Inter, system-ui, sans-serif"
        fontSize="16"
        fontWeight="600"
        letterSpacing="-0.2"
        fill={text}
      >
        Meridian Signal
      </text>
    </svg>
  );
}
