import type { MetadataRoute } from "next";
import { industries, solutions } from "@/content/site";
import { listArticles } from "@/lib/articles";
import { SITE_URL } from "@/lib/utils";

export default function sitemap(): MetadataRoute.Sitemap {
  const pages = [
    "/",
    "/platform",
    "/pricing",
    "/security",
    "/developers",
    "/methodology",
    "/resources",
    "/company",
    "/contact",
    "/legal/privacy",
    "/legal/terms",
    "/legal/cookies",
  ];
  const dynamic = [
    ...solutions.map((s) => `/solutions/${s.slug}`),
    ...industries.map((i) => `/industries/${i.slug}`),
  ];
  const articles = listArticles().map((a) => ({
    url: `${SITE_URL}/resources/${a.slug}`,
    lastModified: a.date,
  }));
  return [...pages, ...dynamic]
    .map((p) => ({ url: `${SITE_URL}${p === "/" ? "" : p}`, lastModified: new Date("2026-11-02") }))
    .concat(articles.map((a) => ({ url: a.url, lastModified: new Date(a.lastModified) })));
}
