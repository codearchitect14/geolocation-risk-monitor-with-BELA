import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";

export type ArticleMeta = {
  slug: string;
  title: string;
  summary: string;
  date: string;
  tags: string[];
  minutes: number;
  image: string;
};

const DIR = path.join(process.cwd(), "src", "content", "articles");

const IMAGE_BY_SLUG: Record<string, string> = {
  "why-place-names-break-news-geocoding": "article-ambiguity",
  "from-headline-to-coordinates": "article-linking",
  "news-and-hazard-feeds-together": "article-feeds",
  "measuring-a-geoparsing-system": "article-measuring",
  "exposure-scoring": "article-exposure",
  "responsible-use-of-automated-disruption-alerts": "article-responsible",
};

export function listArticles(): ArticleMeta[] {
  return fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith(".mdx"))
    .map((file) => {
      const slug = file.replace(/\.mdx$/, "");
      const { data, content } = matter(fs.readFileSync(path.join(DIR, file), "utf8"));
      const words = content.split(/\s+/).filter(Boolean).length;
      return {
        slug,
        title: String(data.title),
        summary: String(data.summary),
        date: String(data.date),
        tags: (data.tags as string[]) ?? [],
        minutes: Math.max(1, Math.round(words / 220)),
        image: IMAGE_BY_SLUG[slug] ?? "article-ambiguity",
      };
    })
    .sort((a, b) => b.date.localeCompare(a.date));
}

export function loadArticle(slug: string): { meta: ArticleMeta; source: string } | null {
  const meta = listArticles().find((a) => a.slug === slug);
  if (!meta) return null;
  const { content } = matter(fs.readFileSync(path.join(DIR, `${slug}.mdx`), "utf8"));
  return { meta, source: content };
}

export const formatDate = (iso: string): string =>
  new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${iso}T00:00:00Z`));
