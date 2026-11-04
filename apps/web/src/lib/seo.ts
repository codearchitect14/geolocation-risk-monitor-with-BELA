import type { Metadata } from "next";
import { BRAND, SITE_URL } from "./utils";

/** Page metadata with canonical URL and a build-time Open Graph image at /og/<key>. */
export function pageMeta(opts: {
  title: string;
  description: string;
  path: string;
  ogKey?: string;
}): Metadata {
  const key = opts.ogKey ?? (opts.path === "/" ? "home" : opts.path.replace(/^\//, "").replace(/\//g, "-"));
  const image = `${SITE_URL}/og/${key}.png`;
  return {
    title: opts.title,
    description: opts.description,
    alternates: { canonical: opts.path },
    openGraph: {
      title: `${opts.title} | ${BRAND}`,
      description: opts.description,
      url: opts.path,
      images: [{ url: image, width: 1200, height: 630, alt: opts.title }],
    },
    twitter: {
      card: "summary_large_image",
      title: opts.title,
      description: opts.description,
      images: [image],
    },
  };
}

export function jsonLd(data: object): { __html: string } {
  return { __html: JSON.stringify(data).replace(/</g, "\\u003c") };
}

export const organizationLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: BRAND,
  url: SITE_URL,
  logo: `${SITE_URL}/icon.svg`,
};
