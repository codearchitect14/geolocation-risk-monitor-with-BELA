import Link from "next/link";
import { CtaBand, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Picture } from "@/components/picture";
import { Card } from "@/components/ui/card";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Company",
  description: "Mission, approach to responsible use, principles and contact details.",
  path: "/company",
});

const PRINCIPLES = [
  {
    t: "Evidence before claims",
    b: "Every figure on this site comes from a measurement in the repository or a cited public source. Where we have not measured something, we say so.",
  },
  {
    t: "Uncertainty is shown",
    b: "Locations carry a level and a radius. A broad report is drawn as broad, and is not turned into a pin.",
  },
  {
    t: "People decide",
    b: "The system orders attention and presents evidence. It does not decide alone, and it does not replace official warnings.",
  },
  {
    t: "Customer locations stay private",
    b: "Asset locations are isolated to the tenant and excluded from platform analytics.",
  },
  {
    t: "Public data, respectfully used",
    b: "We follow the terms of each source, identify ourselves to services that require it, and give credit.",
  },
];

export default function CompanyPage() {
  return (
    <>
      <PageHero
        eyebrow="Company"
        title="Make disruption understandable to the people who have to act on it"
        aside={
          <Picture
            name="company"
            alt="Network of connected points in blue and teal"
            priority
            className="aspect-[16/10] w-full rounded-card object-cover shadow-e2"
          />
        }
      >
        Meridian Signal is a demonstration product. It shows how entity-aware place linking can turn public
        reports into exposure for the sites an organization cares about.
      </PageHero>
      <Section tone="white">
        <SectionHeading eyebrow="Approach" title="Responsible use">
          Signals are situational awareness and not official warnings. The product is designed for teams who
          verify before acting: it shows sources, states uncertainty and keeps an audit trail. It monitors
          places that an organization registers, and it does not track people. Read more in{" "}
          <Link
            href="/resources/responsible-use-of-automated-disruption-alerts"
            className="text-brand-600 underline"
          >
            our article on responsible use
          </Link>
          .
        </SectionHeading>
      </Section>
      <Section>
        <SectionHeading eyebrow="Principles" title="How we work" />
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {PRINCIPLES.map((p) => (
            <Card key={p.t}>
              <h3 className="text-h4">{p.t}</h3>
              <p className="mt-2 text-slate-700">{p.b}</p>
            </Card>
          ))}
        </div>
      </Section>
      <Section tone="white">
        <SectionHeading eyebrow="Contact" title="Get in touch" />
        <p className="max-w-2xl text-slate-700">
          Use the{" "}
          <Link href="/contact" className="text-brand-600 underline">
            contact form
          </Link>{" "}
          for demonstrations, questions, security reports and corrections. Submissions are stored in the
          platform database and read by the team.
        </p>
      </Section>
      <CtaBand />
    </>
  );
}
