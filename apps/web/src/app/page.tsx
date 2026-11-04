import { ArrowRight, Database, KeyRound, Lock, ScrollText, ShieldCheck } from "lucide-react";
import Link from "next/link";
import {
  AlertsWithoutContext,
  LocalReportsFirst,
  SameNameDifferentPlace,
  StepAlert,
  StepFeeds,
  StepLink,
  StepSites,
} from "@/components/art/illustrations";
import { ExposureList, IncidentCard, ProductMock } from "@/components/art/product-mock";
import { Icon } from "@/components/icons";
import { Picture } from "@/components/picture";
import { CtaBand, DemoActions, Footnote, Section, SectionHeading } from "@/components/site/blocks";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Reveal } from "@/components/ui/reveal";
import { Stepper } from "@/components/ui/misc";
import { capabilities, industries, sources } from "@/content/site";
import { listArticles, formatDate } from "@/lib/articles";
import { formatInt, loadPublicStats, metrics, pct, points } from "@/lib/metrics";
import { jsonLd, organizationLd, pageMeta } from "@/lib/seo";
import { ProductTabs } from "./product-tabs";

export const revalidate = 300;
export const metadata = pageMeta({
  title: "Operational disruption intelligence",
  description:
    "Entity-aware monitoring links news and public hazard feeds to the exact places and assets that matter to you.",
  path: "/",
});

const PROBLEMS = [
  {
    title: "Same name, different place",
    body: "Alexandria, Birmingham and Springfield each name many places. Picking the wrong one puts an incident on the wrong continent.",
    art: SameNameDifferentPlace,
  },
  {
    title: "Local reports arrive first, in local words",
    body: "The first account of a closure usually uses the local name of a facility. Feeds and keyword alerts do not recognize it.",
    art: LocalReportsFirst,
  },
  {
    title: "Alerts without context",
    body: "An alert that does not say where, how certain and near which asset sends the team to look for the answer themselves.",
    art: AlertsWithoutContext,
  },
];

const STEPS = [
  {
    title: "Add your sites and routes",
    body: "Upload a spreadsheet or register assets one by one, with a criticality rating for each.",
    visual: <StepSites className="h-24 w-full" />,
  },
  {
    title: "Ingest news and hazard feeds",
    body: "Public earthquake, weather and fire records arrive together with news reports.",
    visual: <StepFeeds className="h-24 w-full" />,
  },
  {
    title: "Link places and score exposure",
    body: "Names become places, incidents get a location and uncertainty, and each asset gets a score.",
    visual: <StepLink className="h-24 w-full" />,
  },
  {
    title: "Alert and brief your teams",
    body: "Rules decide who is told, and daily or weekly briefings summarize what changed.",
    visual: <StepAlert className="h-24 w-full" />,
  },
];

const SECURITY = [
  {
    icon: Lock,
    title: "Encryption in transit and at rest",
    body: "Traffic uses TLS, and secrets stored by the platform are encrypted.",
  },
  {
    icon: KeyRound,
    title: "Role-based access with multi-factor authentication",
    body: "Roles limit actions, and administrators are required to use a second factor.",
  },
  {
    icon: Database,
    title: "Tenant isolation of asset locations",
    body: "Row level security in the database keeps each tenant's sites private.",
  },
  {
    icon: ScrollText,
    title: "Tamper-evident audit log",
    body: "Each entry is chained to the one before it, so edits are detectable.",
  },
];

export default async function HomePage() {
  const stats = await loadPublicStats();
  const articles = listArticles().slice(0, 3);
  const proof = [
    {
      value: formatInt(stats?.places_indexed ?? metrics.places_indexed),
      label: "Places and facilities indexed",
      note: "Gazetteer entries linked to Wikidata and GeoNames.",
    },
    {
      value: `${metrics.median_error_km} km`,
      label: "Median location error",
      note: `Gold set of public corpora, test split. Mean error is much larger (see methodology).`,
    },
    {
      value: stats ? formatInt(stats.incidents_30d) : "Not available",
      label: "Incidents processed, last 30 days",
      note: stats
        ? "Hazard and news incidents in the demonstration database."
        : "Shown when the data service is reachable.",
    },
    {
      value: points(metrics.acc_161km_ambiguous, metrics.acc_161km_best_gazetteer_baseline_ambiguous),
      label: "Gain on ambiguous names",
      note: `${pct(metrics.acc_161km_ambiguous)} against ${pct(metrics.acc_161km_best_gazetteer_baseline_ambiguous)} for the best gazetteer baseline, within 161 km.`,
    },
  ];

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(organizationLd)} />
      <section className="relative overflow-hidden border-b border-line bg-white">
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
          style={{
            background:
              "radial-gradient(60% 50% at 85% 20%, #E6EFFB 0%, transparent 70%), radial-gradient(40% 40% at 100% 80%, #D5F1F1 0%, transparent 70%)",
          }}
        />
        <div className="container-page relative">
          <div className="content-width grid items-center gap-12 py-14 lg:grid-cols-[1fr_1.1fr] lg:py-24">
            <div>
              <p className="mb-4 text-small font-semibold uppercase tracking-wider text-teal-700">
                Operational disruption intelligence
              </p>
              <h1 className="text-[2.5rem] leading-[2.9rem] lg:text-display lg:leading-[3.75rem]">
                Know what is happening near your operations, as it is reported.
              </h1>
              <p className="mt-6 max-w-xl text-[1.125rem] leading-8 text-slate-700">
                Entity-aware monitoring links news and public hazard feeds to the exact places and assets that
                matter to you, so your teams see credible disruption before it reaches the schedule.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <DemoActions />
              </div>
              <p className="mt-6 max-w-lg text-caption text-slate-600">
                Signals are situational awareness and not official warnings. Follow local authorities.
              </p>
            </div>
            <div className="relative pb-4 sm:pb-32">
              <ProductMock tab="map" />
              <div className="absolute bottom-0 left-0 hidden w-64 sm:block lg:-left-8">
                <IncidentCard />
              </div>
              <div className="absolute -right-2 top-10 hidden w-48 xl:block">
                <ExposureList />
              </div>
              <p className="mt-3 text-caption text-slate-600">
                Illustrative interface rendering. Outlines are Natural Earth; markers are recent hazard
                records from the demonstration database.
              </p>
            </div>
          </div>
        </div>
      </section>

      <Section tone="white" label="Evidence" className="!py-10 lg:!py-14">
        <dl className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {proof.map((p) => (
            <div key={p.label}>
              <dt className="text-small font-medium text-ink">{p.label}</dt>
              <dd>
                <span className="block text-[2rem] font-semibold leading-10 tracking-tight text-ink tabular">
                  {p.value}
                </span>
                <Footnote>
                  {p.note}{" "}
                  <Link href="/methodology" className="underline underline-offset-2">
                    Methodology
                  </Link>
                </Footnote>
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section>
        <SectionHeading
          eyebrow="The problem"
          title="Three reasons disruption signals fail the people who need them"
        />
        <div className="grid gap-6 md:grid-cols-3">
          {PROBLEMS.map((p, i) => (
            <Reveal key={p.title} delay={i * 0.05}>
              <Card hover className="h-full">
                <p.art className="mb-5 h-36 w-full" />
                <h3 className="text-h4">{p.title}</h3>
                <p className="mt-2 text-slate-700">{p.body}</p>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section tone="white">
        <SectionHeading eyebrow="How it works" title="From your sites to a briefing in four steps" />
        <Stepper steps={STEPS} />
      </Section>

      <Section>
        <SectionHeading eyebrow="Capabilities" title="One pipeline from text to exposure" />
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {capabilities.map((c) => (
            <Link
              key={c.title}
              href={c.href}
              className="group block rounded-card focus-visible:outline-offset-4"
            >
              <Card hover className="h-full">
                <span className="mb-4 flex size-11 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
                  <Icon name={c.icon} className="size-6" />
                </span>
                <h3 className="text-h4">{c.title}</h3>
                <p className="mt-2 text-slate-700">{c.body}</p>
                <span className="mt-4 inline-flex items-center gap-1 text-small font-medium text-brand-600">
                  Learn more{" "}
                  <ArrowRight
                    className="size-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </span>
              </Card>
            </Link>
          ))}
        </div>
      </Section>

      <Section tone="white">
        <SectionHeading eyebrow="Product" title="What your teams work with" />
        <ProductTabs />
      </Section>

      <Section>
        <SectionHeading eyebrow="Industries" title="Built for teams that run on physical networks" />
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {industries.map((i) => (
            <Link
              key={i.slug}
              href={`/industries/${i.slug}`}
              className="group relative block overflow-hidden rounded-card focus-visible:outline-offset-4"
            >
              <Picture
                name={i.image}
                alt={i.imageAlt}
                sizes="(min-width: 1024px) 360px, (min-width: 640px) 50vw, 100vw"
                className="aspect-[4/3] w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
              />
              <div
                className="absolute inset-0 bg-gradient-to-t from-ink/90 via-ink/20 to-transparent"
                aria-hidden="true"
              />
              <div className="absolute inset-x-0 bottom-0 p-5">
                <p className="text-h4 font-semibold text-white">{i.title}</p>
                <p className="text-small text-slate-200">{i.short}</p>
              </div>
            </Link>
          ))}
        </div>
      </Section>

      <Section tone="white">
        <SectionHeading eyebrow="Data coverage" title="Public sources, with their limits stated">
          Hazard feeds are fused with news. National Weather Service alerts cover the United States only.
          Counts below are read from the demonstration database for the last 30 days.
        </SectionHeading>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {sources.map((s) => {
            const count = stats?.event_sources_30d[s.kind];
            return (
              <li key={s.name} className="rounded-card border border-line bg-page p-4">
                <p className="font-medium text-ink">{s.name}</p>
                <p className="text-small text-slate-600">{s.note}</p>
                {s.kind !== "ref" ? (
                  <p className="mt-2 text-small tabular text-ink">
                    {count !== undefined ? `${formatInt(count)} source records` : "No records in this period"}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
        <Footnote>
          FIRMS and GDELT records depend on keys and rate limits in each environment. A zero count means none
          were ingested here, not that nothing happened.
        </Footnote>
      </Section>

      <Section tone="ink" label="Security">
        <SectionHeading tone="dark" eyebrow="Security" title="Designed to keep your site locations private">
          Controls are designed to align with common security frameworks. No certification is claimed.
        </SectionHeading>
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {SECURITY.map((s) => (
            <li key={s.title}>
              <s.icon className="size-7 text-[#8FC2FF]" aria-hidden="true" />
              <p className="mt-3 font-semibold text-white">{s.title}</p>
              <p className="mt-1 text-small text-slate-300">{s.body}</p>
            </li>
          ))}
        </ul>
        <Button asChild variant="outlineInverse" className="mt-8">
          <Link href="/security">Read the security overview</Link>
        </Button>
        <ShieldCheck className="sr-only" aria-hidden="true" />
      </Section>

      <Section>
        <SectionHeading eyebrow="Insights" title="Latest from the team" />
        <div className="grid gap-6 md:grid-cols-3">
          {articles.map((a) => (
            <Link
              key={a.slug}
              href={`/resources/${a.slug}`}
              className="group block focus-visible:outline-offset-4"
            >
              <Card hover className="h-full overflow-hidden !p-0">
                <Picture
                  name={a.image}
                  alt=""
                  sizes="(min-width: 768px) 360px, 100vw"
                  className="aspect-[16/9] w-full object-cover"
                />
                <div className="p-5">
                  <p className="text-caption text-slate-600">
                    {formatDate(a.date)} · {a.minutes} min read
                  </p>
                  <h3 className="mt-1 text-h4 group-hover:text-brand-600">{a.title}</h3>
                  <p className="mt-2 text-small text-slate-700">{a.summary}</p>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </Section>

      <CtaBand />
    </>
  );
}
