import Link from "next/link";
import { notFound } from "next/navigation";
import { CtaBand } from "@/components/site/blocks";
import { Mdx } from "@/components/mdx";
import { Picture } from "@/components/picture";
import { Breadcrumbs } from "@/components/ui/misc";
import { formatDate, listArticles, loadArticle } from "@/lib/articles";
import { jsonLd, pageMeta } from "@/lib/seo";
import { BRAND, DISCLAIMER, SITE_URL } from "@/lib/utils";

export const dynamicParams = false;
export const generateStaticParams = () => listArticles().map((a) => ({ slug: a.slug }));

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const a = loadArticle((await params).slug);
  return a
    ? pageMeta({
        title: a.meta.title,
        description: a.meta.summary,
        path: `/resources/${a.meta.slug}`,
        ogKey: `resources-${a.meta.slug}`,
      })
    : {};
}

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const a = loadArticle((await params).slug);
  if (!a) notFound();
  const { meta } = a;
  const others = listArticles()
    .filter((x) => x.slug !== meta.slug)
    .slice(0, 2);
  const ld = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: meta.title,
    description: meta.summary,
    datePublished: meta.date,
    author: { "@type": "Organization", name: BRAND },
    publisher: { "@type": "Organization", name: BRAND },
    mainEntityOfPage: `${SITE_URL}/resources/${meta.slug}`,
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(ld)} />
      <article className="bg-white">
        <header className="border-b border-line">
          <div className="container-page">
            <div className="content-width py-12 lg:py-16">
              <Breadcrumbs
                items={[
                  { label: "Home", href: "/" },
                  { label: "Resources", href: "/resources" },
                  { label: meta.title },
                ]}
              />
              <h1 className="mt-6 max-w-3xl text-[2.25rem] leading-[2.75rem] lg:text-h1 lg:leading-[3.125rem]">
                {meta.title}
              </h1>
              <p className="mt-4 max-w-2xl text-[1.125rem] leading-8 text-slate-700">{meta.summary}</p>
              <p className="mt-5 text-small text-slate-600">
                {BRAND} · <time dateTime={meta.date}>{formatDate(meta.date)}</time> · {meta.minutes} min read
              </p>
            </div>
          </div>
        </header>
        <div className="container-page">
          <div className="content-width py-10 lg:py-14">
            <Picture
              name={meta.image}
              alt=""
              priority
              sizes="(min-width: 1120px) 1120px, 100vw"
              className="mb-10 aspect-[21/9] w-full rounded-card object-cover"
            />
            <Mdx source={a.source} />
            <p className="prose-article mt-12 border-t border-line pt-6 text-small text-slate-600">
              {DISCLAIMER}
            </p>
          </div>
        </div>
      </article>
      <section className="section-pad">
        <div className="container-page">
          <div className="content-width">
            <h2 className="text-h3">Continue reading</h2>
            <ul className="mt-6 grid gap-4 md:grid-cols-2">
              {others.map((o) => (
                <li key={o.slug}>
                  <Link
                    href={`/resources/${o.slug}`}
                    className="block rounded-card border border-line bg-white p-5 hover:shadow-e2"
                  >
                    <span className="font-semibold text-ink">{o.title}</span>
                    <span className="mt-1 block text-small text-slate-700">{o.summary}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
      <CtaBand />
    </>
  );
}
