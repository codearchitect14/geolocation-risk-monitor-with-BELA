import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Custom type scale names (text-body, text-small, ...) must be known as font sizes, or text-white after text-body is dropped.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: { "font-size": [{ text: ["display", "h1", "h2", "h3", "h4", "body", "small", "caption"] }] },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
export const BRAND = "Meridian Signal";
export const DISCLAIMER =
  "Signals are situational awareness and not official warnings. Follow local authorities.";
