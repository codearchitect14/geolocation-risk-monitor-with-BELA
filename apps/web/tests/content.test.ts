import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { evalRows } from "@/content/eval";
import { industries, plans, solutions } from "@/content/site";
import { listArticles, loadArticle } from "@/lib/articles";
import { metrics, pct } from "@/lib/metrics";

const SRC = path.resolve(process.cwd(), "src");

function walk(dir: string): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
}
const textFiles = walk(SRC).filter((f) => /\.(tsx?|mdx|json|css)$/.test(f) && !f.endsWith("world.json"));

describe("conventions", () => {
  it("contains no em dash", () => {
    const bad = textFiles.filter((f) => fs.readFileSync(f, "utf8").includes(String.fromCharCode(0x2014)));
    expect(bad).toEqual([]);
  });
  it("names no AI assistant or vendor", () => {
    const pattern = /\b(claude|anthropic|openai|chatgpt|copilot|gemini|llama\.cpp)\b/i;
    const bad = textFiles.filter((f) => pattern.test(fs.readFileSync(f, "utf8")));
    expect(bad).toEqual([]);
  });
});

describe("articles", () => {
  const articles = listArticles();
  it("has six articles", () => expect(articles).toHaveLength(6));
  for (const a of articles) {
    it(`${a.slug} is 900 to 1,400 words`, () => {
      const words = (loadArticle(a.slug)?.source ?? "").split(/\s+/).filter(Boolean).length;
      expect(words).toBeGreaterThanOrEqual(900);
      expect(words).toBeLessThanOrEqual(1400);
    });
  }
});

describe("figures", () => {
  it("evaluation table matches metrics.json for the shipped configuration", () => {
    const s6 = evalRows.find((r) => r.id === "S6");
    expect(s6?.acc161).toBe(pct(metrics.acc_161km));
    expect(s6?.amb161).toBe(pct(metrics.acc_161km_ambiguous));
    expect(evalRows.find((r) => r.id === "S2")?.amb161).toBe(
      pct(metrics.acc_161km_best_gazetteer_baseline_ambiguous),
    );
    expect(Number(s6?.median)).toBe(metrics.median_error_km);
  });
  it("bundled metrics.json equals the repository copy", () => {
    const repo = JSON.parse(
      fs.readFileSync(path.resolve(process.cwd(), "../../public/metrics.json"), "utf8"),
    );
    expect(repo).toEqual(metrics);
  });
  it("plans match the demonstration price list", () => {
    expect(plans.map((p) => [p.id, p.price, p.assets, p.overagePrice])).toEqual([
      ["starter", 499, 50, 60],
      ["professional", 1999, 500, 200],
      ["enterprise", 8000, 5000, 400],
    ]);
  });
});

describe("pages", () => {
  it("has four solutions and six industries with scenarios", () => {
    expect(solutions).toHaveLength(4);
    expect(industries).toHaveLength(6);
    for (const i of industries) expect(i.scenario.body.length).toBeGreaterThan(100);
  });
  it("legal and site text carries the disclaimer in the footer catalogs", () => {
    for (const l of ["en", "es", "fr", "de"]) {
      const m = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), `messages/${l}.json`), "utf8"));
      expect(m.footer.disclaimer.length).toBeGreaterThan(30);
    }
  });
});
