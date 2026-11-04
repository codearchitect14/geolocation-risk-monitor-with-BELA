import { Check, Minus } from "lucide-react";
import Link from "next/link";
import { CtaBand, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Faq } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { comparison, plans, pricingFaq } from "@/content/site";
import { formatInt } from "@/lib/metrics";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Pricing",
  description:
    "Three plans priced by the number of monitored assets. Illustrative pricing for the demonstration environment.",
  path: "/pricing",
});

export default function PricingPage() {
  return (
    <>
      <PageHero eyebrow="Pricing" title="Priced by the number of assets you monitor">
        Each plan includes the full pipeline. The difference is the asset limit and the administrative
        features around it.
        <span className="mt-4 block">
          <Badge tone="illustrative">Illustrative pricing for the demo environment</Badge>
        </span>
      </PageHero>
      <Section>
        <div className="grid gap-6 lg:grid-cols-3">
          {plans.map((p) => (
            <Card
              key={p.id}
              className={p.id === "professional" ? "border-brand-500 ring-2 ring-brand-500/20" : ""}
            >
              <h2 className="text-h3">{p.name}</h2>
              <p className="mt-1 text-slate-600">{p.blurb}</p>
              <p className="mt-6">
                <span className="text-[2.5rem] font-semibold tracking-tight text-ink tabular">
                  ${formatInt(p.price)}
                </span>
                <span className="text-slate-600"> per month</span>
              </p>
              <p className="text-small text-slate-600 tabular">
                Up to {formatInt(p.assets)} assets. Additional {p.overageUnit} assets: ${p.overagePrice} per
                month.
              </p>
              <ul className="mt-6 space-y-3">
                {p.features.map((f) => (
                  <li key={f} className="flex gap-3">
                    <Check className="mt-1 size-5 shrink-0 text-success" aria-hidden="true" />
                    {f}
                  </li>
                ))}
              </ul>
              <Button
                asChild
                className="mt-8 w-full"
                variant={p.id === "professional" ? "primary" : "secondary"}
              >
                <Link href={`/contact?plan=${p.id}`}>Request a demo</Link>
              </Button>
            </Card>
          ))}
        </div>
      </Section>
      <Section tone="white">
        <SectionHeading eyebrow="Compare" title="Feature comparison" />
        <div
          tabIndex={0}
          role="region"
          aria-label="Plan comparison table"
          className="overflow-x-auto rounded-card border border-line"
        >
          <table className="w-full min-w-[640px] text-left">
            <caption className="sr-only">Feature comparison of the three plans</caption>
            <thead className="bg-slate-50">
              <tr>
                <th scope="col" className="p-4 font-semibold text-ink">
                  Feature
                </th>
                {plans.map((p) => (
                  <th key={p.id} scope="col" className="p-4 font-semibold text-ink">
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {comparison.map((row) => (
                <tr key={row.feature} className="border-t border-line">
                  <th scope="row" className="p-4 font-normal text-slate-800">
                    {row.feature}
                  </th>
                  {row.values.map((v, i) => (
                    <td key={i} className="p-4 text-slate-700 tabular">
                      {v === "Included" ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Check className="size-4 text-success" aria-hidden="true" />
                          Included
                        </span>
                      ) : v === "Not included" ? (
                        <span className="inline-flex items-center gap-1.5 text-slate-600">
                          <Minus className="size-4" aria-hidden="true" />
                          Not included
                        </span>
                      ) : (
                        v
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-caption text-slate-600">
          Plan gating of features is illustrative in the demonstration environment.
        </p>
      </Section>
      <Section>
        <SectionHeading eyebrow="Overage" title="How monitored asset limits work">
          Assets above the limit are billed in blocks of 25 at your plan&apos;s overage price. For example,
          530 assets on Professional is 30 above the limit, which is two blocks of 25, or $400 per month in
          addition to the plan price. Monitoring is never paused for exceeding a limit.
        </SectionHeading>
        <Faq items={pricingFaq} />
      </Section>
      <CtaBand />
    </>
  );
}
