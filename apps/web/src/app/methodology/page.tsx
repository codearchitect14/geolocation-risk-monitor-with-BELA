import { CtaBand, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { byCorpus, evalRows, failures } from "@/content/eval";
import { formatInt, metrics, pct, points } from "@/lib/metrics";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Methodology",
  description: "Data sources, coverage limits, models, evaluation design, results and known limitations.",
  path: "/methodology",
});

function Table({
  caption,
  head,
  rows,
  className,
}: {
  caption: string;
  head: string[];
  rows: (string | number)[][];
  className?: string;
}) {
  return (
    <div
      tabIndex={0}
      role="region"
      aria-label={caption}
      className={`overflow-x-auto rounded-card border border-line bg-white ${className ?? ""}`}
    >
      <table className="w-full min-w-[560px] text-left text-small">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="p-3 font-semibold text-ink">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line">
              {r.map((c, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="p-3 font-normal text-slate-800">
                    {c}
                  </th>
                ) : (
                  <td key={j} className="p-3 tabular text-slate-700">
                    {c}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MethodologyPage() {
  return (
    <>
      <PageHero eyebrow="Methodology" title="How the system works and how it is measured">
        Every figure on this site comes from this page&apos;s sources. Where a measurement does not exist, we
        say so.
      </PageHero>

      <Section tone="white" id="sources">
        <SectionHeading eyebrow="Data" title="Sources and terms" />
        <Table
          caption="Data sources"
          head={["Source", "Used for", "Coverage"]}
          rows={[
            ["USGS earthquake feed", "Earthquake incidents", "Worldwide"],
            ["National Weather Service alerts", "Weather incidents with zone polygons", "United States only"],
            ["NASA FIRMS", "Satellite fire detections, clustered by density", "Worldwide, requires a key"],
            ["GDELT and news datasets", "News reports and metadata", "Worldwide, uneven"],
            ["Wikidata", "Entities, types and coordinates (CC0)", "Worldwide"],
            [
              "GeoNames",
              "Gazetteer names and aliases (CC BY 4.0)",
              `Gazetteer of ${formatInt(metrics.places_indexed)} places`,
            ],
            ["Natural Earth", "Country and region boundaries (public domain)", "Worldwide"],
          ]}
        />
        <p className="mt-3 text-caption text-slate-600">
          Public data is used under its own terms. The licensing register in the repository lists each source
          and its license.
        </p>
      </Section>

      <Section id="feeds">
        <SectionHeading eyebrow="Coverage" title="Coverage limits" />
        <ul className="list-disc space-y-3 pl-5 text-[1.0625rem] text-slate-700">
          <li>
            Weather alerts are available for the United States only. Elsewhere, weather incidents rely on
            news.
          </li>
          <li>
            News coverage favors regions that are widely reported. Small places are covered thinly, and an
            absence of reports is not evidence of an absence of events.
          </li>
          <li>Evaluation was performed on English text. Other languages have not been evaluated.</li>
          <li>
            Feed availability depends on keys and rate limits in each environment. The sources page shows the
            state of each feed, and incidents are marked with reduced confidence when a component is down.
          </li>
        </ul>
      </Section>

      <Section tone="white">
        <SectionHeading eyebrow="Models" title="What runs, and what it is allowed to decide" />
        <ul className="list-disc space-y-3 pl-5 text-[1.0625rem] text-slate-700">
          <li>
            <strong>Entity linking.</strong> A bi-encoder entity linking model detects place mentions and
            links them to Wikidata entities. A type filter keeps places and facilities.
          </li>
          <li>
            <strong>Gazetteer fallback and re-ranking.</strong> For mentions the linker rejects, GeoNames
            names and aliases propose candidates. A learned re-ranker uses context features: region named in
            the text, distance to other places, population and type fit.
          </li>
          <li>
            <strong>Local language model.</strong> A model running on local hardware adjudicates uncertain
            cases among stored candidates, classifies event type, and writes briefing summaries that are
            checked against the data. It cannot invent places and never decides alone whether an alert is
            raised.
          </li>
          <li>
            <strong>Event location selector.</strong> Rules and a model choose one location per event from all
            resolved places and return a level and an uncertainty radius.
          </li>
        </ul>
        <p className="mt-4 text-small text-slate-600">
          The repository includes a model card with intended use, training data and known issues.
        </p>
      </Section>

      <Section id="evaluation">
        <SectionHeading eyebrow="Evaluation" title="Design">
          Public geoparsing corpora (LGL, TR-News, GeoWebNews, GeoVirus and a sample of WikToR) were split by
          document hash into development and test halves. The test split has 787 documents and 6,466 gold
          place mentions. The development half trained the re-ranker and fitted calibration, and every figure
          below is from the test split. A gold mention that the system did not detect counts as wrong unless a
          column says otherwise. The ambiguous subset is the 2,969 mentions whose name matches at least two
          places in the gazetteer.
        </SectionHeading>
        <Table
          caption="Results on the test split"
          head={["System", "Within 25 km", "Within 161 km", "Median km", "Mean km", "Ambiguous, 161 km"]}
          rows={evalRows.map((r) => [`${r.id}: ${r.name}`, r.acc25, r.acc161, r.median, r.mean, r.amb161])}
        />
        <p className="mt-3 text-slate-700">
          The shipped configuration ({metrics.system}) reaches {pct(metrics.acc_161km)} within 161 km on all
          mentions and {pct(metrics.acc_161km_ambiguous)} on ambiguous names, against{" "}
          {pct(metrics.acc_161km_best_gazetteer_baseline_ambiguous)} for the best gazetteer-only baseline: a
          gain of {points(metrics.acc_161km_ambiguous, metrics.acc_161km_best_gazetteer_baseline_ambiguous)}{" "}
          on ambiguous names. Median error is {metrics.median_error_km} km, and the mean is far higher because
          some mentions are placed on the wrong continent.
        </p>
        <h3 className="mt-10 text-h4">By corpus, within 161 km</h3>
        <Table
          className="mt-3"
          caption="Accuracy by corpus"
          head={["Corpus", "Largest-population baseline (S1)", "Shipped configuration (S6)"]}
          rows={byCorpus.map((r) => [r.corpus, r.s1, r.s6])}
        />
        <p className="mt-3 text-caption text-slate-600">
          The baseline wins on TR-News, where mentions are mostly well-known cities. The gain comes from the
          harder corpora.
        </p>
        <h3 className="mt-10 text-h4">Where the shipped configuration fails</h3>
        <Table
          className="mt-3"
          caption="Outcome categories"
          head={["Outcome", "Share of gold mentions"]}
          rows={failures.map((r) => [r.outcome, r.share])}
        />
      </Section>

      <Section tone="white">
        <SectionHeading eyebrow="Limits" title="Known limitations" />
        <ul className="list-disc space-y-3 pl-5 text-[1.0625rem] text-slate-700">
          <li>
            There is no labeled set of real events, so event type and severity accuracy are not measured. A
            small author-written headline set is used only as a smoke test.
          </li>
          <li>Detection delay between hazard feeds and news has not been measured.</li>
          <li>Event location confidence is not calibrated against real events.</li>
          <li>
            Exposure scoring was checked on synthetic scenarios. At the lowest alert level recall was 0.93 and
            precision 0.38, and the thresholds are a choice for each organization.
          </li>
          <li>
            Location confirmation rate, derived from reviewer feedback, is a proxy: reviewers are a
            self-selected sample.
          </li>
          <li>The local model slows news ingestion. Throughput depends on hardware.</li>
        </ul>
      </Section>

      <Section>
        <SectionHeading eyebrow="Corrections" title="How corrections work">
          Reviewers can mark a location as wrong and choose another candidate from those stored for the
          mention. Corrections enter a review queue. A correction is added to a candidate training file only
          when the user gave consent for that purpose. Nothing is learned automatically.
        </SectionHeading>
        <p className="rounded-card border border-line bg-white p-5 text-slate-800">
          Signals are situational awareness derived from public news and public data feeds. They are not
          official warnings. Verify with local authorities and follow their guidance.
        </p>
        <p className="mt-4 text-caption text-slate-600">
          Figures last generated {metrics.generated_at.slice(0, 10)} from {metrics.evaluation}.
        </p>
      </Section>
      <CtaBand />
    </>
  );
}
