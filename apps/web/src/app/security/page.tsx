import { CtaBand, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Picture } from "@/components/picture";
import { Card } from "@/components/ui/card";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Security",
  description:
    "Architecture, data protection, access control, audit, retention and an honest list of what is not claimed.",
  path: "/security",
});

const BLOCKS = [
  {
    title: "Architecture",
    body: "A web application and API sit in front of a PostgreSQL database with PostGIS. Background workers ingest feeds and run linking. The language model runs locally, so article text is not sent to an outside service. The browser talks to one origin, and the web application proxies the API.",
  },
  {
    title: "Data protection",
    body: "Traffic is encrypted with TLS. Secrets that the platform stores, such as webhook signing secrets and authenticator seeds, are encrypted with a key held outside the database. Passwords are stored as salted hashes with a memory-hard algorithm. Backups follow the same protections as the database.",
  },
  {
    title: "Access control",
    body: "Eight permissions are grouped into roles and enforced on the server. Sessions use short-lived signed tokens in cookies that scripts cannot read, with rotating refresh tokens and detection of token reuse. State-changing requests carry a CSRF token. Administrator roles must use multi-factor authentication. Sign-in is rate limited by account and by address, with progressive lockout and generic error messages.",
  },
  {
    title: "Tenant isolation",
    body: "Each customer is a tenant. Row level security in the database restricts every query to the tenant of the request, so a defect in application code cannot return another tenant's rows. Automated tests check every role against every endpoint group and attempt cross-tenant access, including spatial queries.",
  },
  {
    title: "Audit",
    body: "Security-relevant actions are written to an audit log. Each entry includes a hash of the previous entry, computed by the database, and the table accepts no updates or deletes, so tampering is detectable. Administrators can review and export the log.",
  },
  {
    title: "Protection of asset locations",
    body: "Asset names and coordinates are visible only inside the tenant. They do not appear in logs, notifications to outside services or platform analytics. Platform analytics use counts by region and level, without names or positions.",
  },
  {
    title: "Retention",
    body: "Tenant data is kept while the account is active. Article text is kept for a limited period for evidence, and incident records keep links to original sources. Retention periods are configurable in the demonstration environment.",
  },
  {
    title: "Responsible use and limitations",
    body: "The platform provides situational awareness from public information. It is not an official warning service and should not be used as the sole basis for safety decisions. It does not track people or vehicles. Article text is treated as untrusted input, and a language model never decides on its own whether an alert is raised.",
  },
];

const NOT_CLAIMED = [
  "No security certification or attestation has been obtained.",
  "No independent penetration test has been performed, and the automated web scan has not yet been run against a complete stack.",
  "Controls are designed to align with common frameworks. That is a statement of intent, not of compliance.",
  "The environment is a demonstration. It is not operated as a production service with a service level.",
  "Coverage and accuracy have limits that are stated on the methodology page.",
];

export default function SecurityPage() {
  return (
    <>
      <PageHero
        eyebrow="Security"
        title="Built to keep your site locations private"
        aside={
          <Picture
            name="server-room"
            alt="Rows of server racks with blue status lights"
            priority
            className="aspect-[16/10] w-full rounded-card object-cover shadow-e2"
          />
        }
      >
        Asset locations are sensitive. The design limits who can see them, records who did, and avoids copying
        them into places where they are not needed.
      </PageHero>
      <Section tone="white">
        <div className="grid gap-6 md:grid-cols-2">
          {BLOCKS.map((b) => (
            <Card key={b.title}>
              <h2 className="text-h4">{b.title}</h2>
              <p className="mt-2 text-slate-700">{b.body}</p>
            </Card>
          ))}
        </div>
      </Section>
      <Section>
        <SectionHeading eyebrow="Plainly stated" title="What is not claimed" />
        <ul className="list-disc space-y-3 pl-5 text-[1.0625rem] text-slate-700">
          {NOT_CLAIMED.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
        <p className="mt-6 text-slate-700">
          To report a security concern, use the{" "}
          <a href="/contact?topic=security" className="font-medium text-brand-600 underline">
            contact form
          </a>{" "}
          and choose the security topic.
        </p>
      </Section>
      <CtaBand />
    </>
  );
}
