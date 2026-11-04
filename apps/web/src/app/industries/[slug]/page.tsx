import { Check } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Picture } from "@/components/picture";
import { CtaBand, DemoActions, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Breadcrumbs } from "@/components/ui/misc";
import { industries } from "@/content/site";
import { pageMeta } from "@/lib/seo";

export const dynamicParams = false;
export const generateStaticParams = () => industries.map((i) => ({ slug: i.slug }));

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const i = industries.find((x) => x.slug === slug);
  return i
    ? pageMeta({
        title: i.title,
        description: `${i.short} Disruption monitoring for ${i.title.toLowerCase()}.`,
        path: `/industries/${i.slug}`,
      })
    : {};
}

export default async function IndustryPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const i = industries.find((x) => x.slug === slug);
  if (!i) notFound();
  return (
    <>
      <PageHero
        eyebrow="Industry"
        title={i.title}
        actions={<DemoActions />}
        aside={
          <Picture
            name={i.image}
            alt={i.imageAlt}
            priority
            className="aspect-[16/10] w-full rounded-card object-cover shadow-e2"
          />
        }
      >
        {i.short} Monitor the places that matter to your operations against public news and hazard feeds.
      </PageHero>
      <Section tone="white">
        <div className="mb-6">
          <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "Industries" }, { label: i.title }]} />
        </div>
        <SectionHeading eyebrow="Typical themes" title="What teams in this industry watch for" />
        <ul className="grid gap-4 sm:grid-cols-2">
          {i.themes.map((t) => (
            <li key={t} className="flex gap-3 rounded-card border border-line bg-page p-4">
              <Check className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
              {t}
            </li>
          ))}
        </ul>
      </Section>
      <Section>
        <Card className="border-dashed !border-slate-400 lg:p-10">
          <Badge tone="illustrative">Illustrative scenario</Badge>
          <h2 className="mt-4 text-h3">{i.scenario.title}</h2>
          <p className="mt-3 max-w-3xl text-[1.0625rem] leading-8 text-slate-700">{i.scenario.body}</p>
          <p className="mt-4 text-caption text-slate-600">
            This scenario is invented to show how the product behaves. It does not describe a real customer or
            a real event.
          </p>
        </Card>
      </Section>
      <Section tone="white">
        <div className="grid gap-12 lg:grid-cols-2">
          <div>
            <SectionHeading title="Recommended workflow" />
            <ol className="space-y-4">
              {i.workflow.map((w, n) => (
                <li key={w} className="flex gap-4">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-small font-semibold text-white tabular">
                    {n + 1}
                  </span>
                  <span className="pt-0.5">{w}</span>
                </li>
              ))}
            </ol>
          </div>
          <div>
            <SectionHeading title="Related capabilities" />
            <ul className="space-y-3">
              {i.related.map((r) => (
                <li key={r.href}>
                  <Link href={r.href} className="font-medium text-brand-600 underline underline-offset-4">
                    {r.title}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>
      <CtaBand />
    </>
  );
}
