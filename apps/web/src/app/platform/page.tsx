import { Check } from "lucide-react";
import Link from "next/link";
import { PipelineDiagram, MapRadius } from "@/components/art/illustrations";
import { ProductMock } from "@/components/art/product-mock";
import { CtaBand, DemoActions, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Button } from "@/components/ui/button";
import { MapSection } from "@/components/map-section";
import { world } from "@/lib/world";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Platform",
  description:
    "From ingestion to briefings: how the platform links places, detects incidents and scores exposure.",
  path: "/platform",
});

const MODULES: {
  id: string;
  title: string;
  body: string;
  items: string[];
  mock?: "map" | "exposure" | "incident" | "analytics";
  radius?: boolean;
}[] = [
  {
    id: "ingestion",
    title: "Ingestion",
    body: "News and public hazard feeds enter one stream. Each record is normalized, de-duplicated and stored with its source.",
    items: [
      "USGS earthquakes, National Weather Service alerts (United States) and NASA FIRMS fire detections",
      "News metadata from public datasets, with article text treated as untrusted input",
      "Feed status shown on the data sources page, with reduced confidence marked when a component is down",
    ],
    mock: "map",
  },
  {
    id: "place-linking",
    title: "Place linking",
    body: "Place names in text become places and facilities with coordinates. Ambiguous names are resolved with context, and unresolved names stay unresolved.",
    items: [
      "Entity linking against Wikidata, with a type filter for places and facilities",
      "Gazetteer fallback and context re-ranking for names the linker rejects",
      "Reviewer corrections kept in a queue, used for model improvement only with consent",
    ],
    mock: "incident",
  },
  {
    id: "incidents",
    title: "Incidents",
    body: "Reports about the same event are grouped into one incident with a type, a level, a status, a location level and an uncertainty radius.",
    items: [
      "Hazard records and news fused, with every original source linked",
      "Status lifecycle from new to resolved, including cancellation",
      "Similar past incidents within 100 km over the previous year",
    ],
    mock: "incident",
  },
  {
    id: "exposure",
    title: "Exposure scoring",
    body: "Distance to the edge of the uncertainty region, severity, source reliability, recency and asset criticality combine into an exposure level.",
    items: [
      "Every component stored with the score, so it can be explained",
      "Points, polygons and lines handled by the database",
      "Country-level incidents never matched against site assets",
    ],
    radius: true,
  },
  {
    id: "alerts",
    title: "Alerts and briefings",
    body: "Rules and watch zones decide who is told. Briefings summarize the period and are exported as PDF or HTML.",
    items: [
      "Polygon, circle and administrative region zones",
      "Quiet hours, maintenance windows, de-duplication and automatic escalation",
      "Mandatory reason when an alert is dismissed, with every change in the audit log",
    ],
    mock: "exposure",
  },
  {
    id: "api",
    title: "API",
    body: "Everything in the application is available through a documented API with keys, rate limits and signed webhooks.",
    items: [
      "Bulk asset upload with a staged review of ambiguous rows",
      "Read alerts and incidents, and locate text on demand",
      "Webhook signatures and SSRF-safe delivery",
    ],
  },
];

export default function PlatformPage() {
  return (
    <>
      <PageHero
        eyebrow="Platform"
        title="One pipeline from public reports to exposed assets"
        actions={<DemoActions />}
      >
        Linking and geolocation run once, when a report arrives. Alerts read the stored result, so every alert
        can be traced back to the words and records that produced it.
      </PageHero>
      <Section tone="white" label="Pipeline">
        <PipelineDiagram className="w-full" />
      </Section>
      {MODULES.map((m, i) => (
        <Section key={m.id} id={m.id} tone={i % 2 === 0 ? "page" : "white"}>
          <div className="grid items-center gap-10 lg:grid-cols-2 [&>*]:min-w-0">
            <div className={i % 2 === 1 ? "lg:order-2" : ""}>
              <SectionHeading eyebrow={`Module ${i + 1}`} title={m.title}>
                {m.body}
              </SectionHeading>
              <ul className="space-y-3">
                {m.items.map((it) => (
                  <li key={it} className="flex gap-3">
                    <Check className="mt-1 size-5 shrink-0 text-success" aria-hidden="true" />
                    <span>{it}</span>
                  </li>
                ))}
              </ul>
              {m.id === "api" ? (
                <Button asChild variant="secondary" className="mt-6">
                  <Link href="/developers">Developer documentation</Link>
                </Button>
              ) : null}
            </div>
            <div className={i % 2 === 1 ? "lg:order-1" : ""}>
              {m.mock ? (
                <ProductMock tab={m.mock} />
              ) : m.radius ? (
                <MapRadius className="w-full rounded-card border border-line" />
              ) : (
                <pre
                  tabIndex={0}
                  className="overflow-x-auto rounded-card bg-ink p-5 text-small leading-6 text-slate-200"
                >
                  <code>{`POST /api/v1/assets/bulk
{ "asset_ids": [...], "criticality": 4 }

GET /api/v1/alerts?status=new
POST /api/v1/locate { "text": "..." }`}</code>
                </pre>
              )}
            </div>
          </div>
        </Section>
      ))}
      <Section>
        <SectionHeading eyebrow="Interactive" title="Recent hazard records on the shared map">
          Markers cluster at low zoom and differ by shape as well as color. These are recent earthquake
          records from the demonstration database. A table with the same data follows the map.
        </SectionHeading>
        <MapSection
          label="Recent hazard records"
          markers={world.incidents.map((p, i) => ({
            id: String(i),
            lon: p.lon,
            lat: p.lat,
            level: Math.min(4, Math.max(1, p.level)) as 1 | 2 | 3 | 4,
            label: `Hazard record ${i + 1}`,
            uncertaintyKm: 40,
          }))}
        />
      </Section>
      <CtaBand />
    </>
  );
}
