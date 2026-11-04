import { notFound } from "next/navigation";
import Link from "next/link";
import { MapRadius } from "@/components/art/illustrations";
import { ProductMock } from "@/components/art/product-mock";
import { CtaBand, DemoActions, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Faq } from "@/components/ui/accordion";
import { Breadcrumbs, Timeline } from "@/components/ui/misc";
import { Card } from "@/components/ui/card";
import { evaluationOutcome, solutions } from "@/content/site";
import { metrics, pct } from "@/lib/metrics";
import { jsonLd, pageMeta } from "@/lib/seo";

export const dynamicParams = false;
export const generateStaticParams = () => solutions.map((s) => ({ slug: s.slug }));

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const s = solutions.find((x) => x.slug === slug);
  return s ? pageMeta({ title: s.title, description: s.summary, path: `/solutions/${s.slug}` }) : {};
}

export default async function SolutionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const s = solutions.find((x) => x.slug === slug);
  if (!s) notFound();
  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: s.faq.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(faqLd)} />
      <PageHero
        eyebrow="Solution"
        title={s.title}
        actions={<DemoActions />}
        aside={<MapRadius className="w-full rounded-card border border-line shadow-e2" />}
      >
        {s.summary}
      </PageHero>
      <Section tone="white">
        <div className="mb-6">
          <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "Solutions" }, { label: s.title }]} />
        </div>
        <div className="grid gap-12 lg:grid-cols-2">
          <div>
            <SectionHeading title="The problem" />
            <p className="text-[1.0625rem] leading-8 text-slate-700">{s.problem}</p>
          </div>
          <div>
            <SectionHeading title="The approach" />
            <ul className="list-disc space-y-3 pl-5 text-slate-700">
              {s.approach.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        </div>
      </Section>
      <Section>
        <SectionHeading eyebrow="Workflow" title="How a team works with it" />
        <div className="grid items-start gap-10 lg:grid-cols-2">
          <Timeline items={s.workflow.map((w, i) => ({ ...w, meta: `Step ${i + 1}` }))} />
          <ProductMock tab="exposure" />
        </div>
      </Section>
      <Section tone="white">
        <SectionHeading eyebrow="Outcomes" title="What has been measured">
          Figures come from the public evaluation set, not from customer deployments. There are no customer
          results to report.
        </SectionHeading>
        <div className="grid gap-5 md:grid-cols-3">
          <Card>
            <p className="text-[2rem] font-semibold tabular text-ink">{pct(metrics.acc_161km_ambiguous)}</p>
            <p className="mt-1 text-slate-700">
              of ambiguous place names located within 161 km, compared with{" "}
              {pct(metrics.acc_161km_best_gazetteer_baseline_ambiguous)} for the best gazetteer baseline.
            </p>
          </Card>
          <Card>
            <p className="text-[2rem] font-semibold tabular text-ink">{metrics.median_error_km} km</p>
            <p className="mt-1 text-slate-700">
              median distance error on the test split. The mean is far higher, so some mentions are badly
              wrong.
            </p>
          </Card>
          <Card>
            <p className="text-[2rem] font-semibold tabular text-ink">{pct(metrics.acc_161km)}</p>
            <p className="mt-1 text-slate-700">
              of all place mentions located within 161 km, counting undetected mentions as errors.
            </p>
          </Card>
        </div>
        <p className="mt-4 text-caption text-slate-600">
          Gain on ambiguous names: {evaluationOutcome()}. See the{" "}
          <Link href="/methodology" className="underline">
            methodology
          </Link>{" "}
          for design, corpora and limits.
        </p>
      </Section>
      <Section>
        <SectionHeading eyebrow="FAQ" title="Questions" />
        <Faq items={s.faq} />
      </Section>
      <CtaBand />
    </>
  );
}
