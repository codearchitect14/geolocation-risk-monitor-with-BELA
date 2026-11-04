import { ImageResponse } from "next/og";
import { industries, solutions } from "@/content/site";
import { listArticles } from "@/lib/articles";

export const dynamic = "force-static";

const STATIC: Record<string, string> = {
  "home.png": "Know what is happening near your operations, as it is reported.",
  "platform.png": "One pipeline from public reports to exposed assets",
  "pricing.png": "Priced by the number of assets you monitor",
  "security.png": "Built to keep your site locations private",
  "developers.png": "A documented API for everything in the application",
  "methodology.png": "How the system works and how it is measured",
  "resources.png": "Notes on place linking and disruption monitoring",
  "company.png": "Make disruption understandable to the people who act on it",
  "contact.png": "Request a demo",
};

function titles(): Record<string, string> {
  const out: Record<string, string> = { ...STATIC };
  for (const s of solutions) out[`solutions-${s.slug}.png`] = s.title;
  for (const i of industries) out[`industries-${i.slug}.png`] = i.title;
  for (const a of listArticles()) out[`resources-${a.slug}.png`] = a.title;
  return out;
}

export function generateStaticParams() {
  return Object.keys(titles()).map((key) => ({ key }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const title = titles()[key] ?? "Operational disruption intelligence";
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        background: "linear-gradient(135deg,#12305A,#0B1B33)",
        color: "#fff",
        padding: 72,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 32, fontWeight: 600 }}>
        <div
          style={{ width: 44, height: 44, borderRadius: 22, border: "5px solid #2F74D8", display: "flex" }}
        />
        Meridian Signal
      </div>
      <div style={{ fontSize: 68, lineHeight: 1.1, fontWeight: 700, letterSpacing: -1.5, maxWidth: 1000 }}>
        {title}
      </div>
      <div style={{ fontSize: 26, color: "#8FC2FF" }}>Operational disruption intelligence</div>
    </div>,
    { width: 1200, height: 630 },
  );
}
