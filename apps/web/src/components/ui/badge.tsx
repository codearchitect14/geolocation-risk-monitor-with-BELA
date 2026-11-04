import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badge = cva("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-caption font-medium", {
  variants: {
    tone: {
      neutral: "bg-slate-100 text-slate-700",
      brand: "bg-brand-100 text-brand-600",
      success: "bg-[#E3F4EC] text-[#14683F]",
      warning: "bg-[#FBEFD9] text-[#8A5200]",
      danger: "bg-[#F9E4E1] text-[#992B20]",
      illustrative: "border border-dashed border-slate-400 bg-white text-slate-700",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

const LEVEL_LABEL = ["", "Level 1, low", "Level 2, moderate", "Level 3, high", "Level 4, severe"] as const;
const LEVEL_COLOR = ["", "#7AA6D8", "#E69F00", "#D55E5E", "#8E1B1B"] as const;

/** Severity badge: color, a shape that changes with level, and the label all carry the level. */
export function SeverityBadge({ level }: { level: 1 | 2 | 3 | 4 }) {
  const color = LEVEL_COLOR[level];
  const shapes = [
    "",
    <circle key="1" cx="6" cy="6" r="4" fill={color} />,
    <rect key="2" x="2" y="2" width="8" height="8" fill={color} />,
    <polygon key="3" points="6,1 11,10 1,10" fill={color} />,
    <polygon key="4" points="6,0.5 11.5,6 6,11.5 0.5,6" fill={color} />,
  ];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-0.5 text-caption font-medium text-ink">
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
        {shapes[level]}
      </svg>
      {LEVEL_LABEL[level]}
    </span>
  );
}
