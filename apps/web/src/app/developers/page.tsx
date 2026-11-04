import Link from "next/link";
import { CtaBand, PageHero, Section, SectionHeading } from "@/components/site/blocks";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { pageMeta } from "@/lib/seo";

export const metadata = pageMeta({
  title: "Developers",
  description: "API overview, authentication, code samples, rate limits and webhook signature verification.",
  path: "/developers",
});

const SAMPLES = {
  upload: {
    label: "Create an asset",
    curl: `curl -X POST https://api.example.org/api/v1/assets \\
  -H "Authorization: Bearer $MS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"name":"Rotterdam terminal","type":"site","criticality":4,
       "geometry":{"type":"Point","coordinates":[4.4,51.95]}}'`,
    python: `import os, requests

r = requests.post(
    "https://api.example.org/api/v1/assets",
    headers={"Authorization": f"Bearer {os.environ['MS_API_KEY']}"},
    json={
        "name": "Rotterdam terminal",
        "type": "site",
        "criticality": 4,
        "geometry": {"type": "Point", "coordinates": [4.4, 51.95]},
    },
    timeout=30,
)
r.raise_for_status()
print(r.json())`,
    js: `const res = await fetch("https://api.example.org/api/v1/assets", {
  method: "POST",
  headers: { Authorization: \`Bearer \${process.env.MS_API_KEY}\`, "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Rotterdam terminal",
    type: "site",
    criticality: 4,
    geometry: { type: "Point", coordinates: [4.4, 51.95] },
  }),
});
if (!res.ok) throw new Error(await res.text());
console.log(await res.json());`,
  },
  alerts: {
    label: "Read alerts",
    curl: `curl "https://api.example.org/api/v1/alerts?status=new&level=high" \\
  -H "Authorization: Bearer $MS_API_KEY"`,
    python: `import os, requests

r = requests.get(
    "https://api.example.org/api/v1/alerts",
    params={"status": "new", "level": "high"},
    headers={"Authorization": f"Bearer {os.environ['MS_API_KEY']}"},
    timeout=30,
)
for alert in r.json()["items"]:
    print(alert["level"], alert["event"]["title"])`,
    js: `const res = await fetch("https://api.example.org/api/v1/alerts?status=new&level=high", {
  headers: { Authorization: \`Bearer \${process.env.MS_API_KEY}\` },
});
const { items } = await res.json();
for (const alert of items) console.log(alert.level, alert.event.title);`,
  },
  locate: {
    label: "Locate text",
    curl: `curl -X POST https://api.example.org/api/v1/locate \\
  -H "Authorization: Bearer $MS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"text":"A fire broke out at a plant near Springfield, Illinois."}'`,
    python: `import os, requests

r = requests.post(
    "https://api.example.org/api/v1/locate",
    headers={"Authorization": f"Bearer {os.environ['MS_API_KEY']}"},
    json={"text": "A fire broke out at a plant near Springfield, Illinois."},
    timeout=60,
)
print(r.json())`,
    js: `const res = await fetch("https://api.example.org/api/v1/locate", {
  method: "POST",
  headers: { Authorization: \`Bearer \${process.env.MS_API_KEY}\`, "Content-Type": "application/json" },
  body: JSON.stringify({ text: "A fire broke out at a plant near Springfield, Illinois." }),
});
console.log(await res.json());`,
  },
} as const;

const VERIFY = `import hashlib, hmac, time

def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    # Header format: "t=<unix seconds>,v1=<hex>[,v1=<hex>]"
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    timestamp = next((v for k, v in parts if k == "t"), "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > tolerance:
        return False
    signed = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")`;

function Code({ children }: { children: string }) {
  return (
    <pre
      tabIndex={0}
      className="overflow-x-auto rounded-control bg-ink p-4 text-small leading-6 text-slate-200"
    >
      <code className="font-mono">{children}</code>
    </pre>
  );
}

export default function DevelopersPage() {
  return (
    <>
      <PageHero
        eyebrow="Developers"
        title="A documented API for everything in the application"
        actions={
          <Button asChild size="lg">
            <Link href="/api/docs">Open the API reference</Link>
          </Button>
        }
      >
        Create and upload assets, read alerts and incidents, create webhooks and locate text. The reference is
        generated from the running service, so it always matches the code.
      </PageHero>
      <Section tone="white">
        <div className="grid gap-8 md:grid-cols-3">
          <div>
            <h2 className="text-h4">Overview</h2>
            <p className="mt-2 text-slate-700">
              All endpoints are under <code className="font-mono text-small">/api/v1</code>. Requests and
              responses are JSON. Errors follow the problem details format with a stable{" "}
              <code className="font-mono text-small">code</code> field.
            </p>
          </div>
          <div>
            <h2 className="text-h4">Authentication</h2>
            <p className="mt-2 text-slate-700">
              Applications use API keys (they begin with msk_) sent as a bearer token or in an X-API-Key
              header. Keys belong to a tenant, carry a role, can be revoked, and are shown once at creation.
              Browser sessions use cookies and a CSRF header, and are not intended for scripts.
            </p>
          </div>
          <div>
            <h2 className="text-h4">Rate limits</h2>
            <p className="mt-2 text-slate-700">
              Limits apply per key and per address. A limited request returns status 429 with a{" "}
              <code className="font-mono text-small">Retry-After</code> header. Back off and retry after that
              interval.
            </p>
          </div>
        </div>
      </Section>
      <Section>
        <SectionHeading eyebrow="Samples" title="Three common calls">
          The host name in these samples is a placeholder. Use the address of your environment.
        </SectionHeading>
        <Tabs defaultValue="upload">
          <TabsList aria-label="Task">
            {Object.entries(SAMPLES).map(([k, v]) => (
              <TabsTrigger key={k} value={k}>
                {v.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {Object.entries(SAMPLES).map(([k, v]) => (
            <TabsContent key={k} value={k} className="mt-6 grid gap-4 lg:grid-cols-3">
              {(
                [
                  ["curl", "curl"],
                  ["Python", "python"],
                  ["JavaScript", "js"],
                ] as const
              ).map(([label, key]) => (
                <div key={key}>
                  <p className="mb-2 text-small font-medium text-ink">{label}</p>
                  <Code>{v[key]}</Code>
                </div>
              ))}
            </TabsContent>
          ))}
        </Tabs>
      </Section>
      <Section tone="white">
        <SectionHeading eyebrow="Webhooks" title="Verify webhook signatures">
          Each delivery carries an X-Meridian-Signature header of the form t=timestamp,v1=signature. The
          signature is an HMAC with SHA-256 over the timestamp, a period and the raw request body, keyed with
          the secret of the endpoint. During a secret rotation the header can carry two v1 values. Compare in
          constant time and reject old timestamps. Destinations that resolve to private network addresses are
          refused when the endpoint is created and again at delivery.
        </SectionHeading>
        <Code>{VERIFY}</Code>
        <p className="mt-3 text-caption text-slate-600">
          Bulk upload of a spreadsheet uses the staged upload endpoints described in the API reference.
        </p>
      </Section>
      <CtaBand />
    </>
  );
}
