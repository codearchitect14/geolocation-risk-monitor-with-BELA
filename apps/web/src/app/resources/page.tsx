import { listArticles } from "@/lib/articles";
import { pageMeta } from "@/lib/seo";
import { PageHero, Section } from "@/components/site/blocks";
import { ResourceList } from "./resource-list";

export const metadata = pageMeta({
  title: "Resources",
  description:
    "Articles on place linking, hazard and news feeds, evaluation, exposure scoring and responsible use.",
  path: "/resources",
});

export default function ResourcesPage() {
  const articles = listArticles();
  const tags = [...new Set(articles.flatMap((a) => a.tags))].sort();
  return (
    <>
      <PageHero eyebrow="Resources" title="Notes on place linking and disruption monitoring">
        Practical articles from the team on how the system works and how it is measured.
      </PageHero>
      <Section>
        <ResourceList articles={articles} tags={tags} />
      </Section>
    </>
  );
}
