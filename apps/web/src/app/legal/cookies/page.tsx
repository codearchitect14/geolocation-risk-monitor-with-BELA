import { PageHero, Section } from "@/components/site/blocks";
import { pageMeta } from "@/lib/seo";
import { Doc } from "../doc";
import { COOKIES } from "../text";

export const metadata = pageMeta({
  title: "Cookie policy",
  description: "The storage this site uses and why.",
  path: "/legal/cookies",
});

export default function Page() {
  return (
    <>
      <PageHero eyebrow="Legal" title="Cookie policy">
        Last updated 2 November 2026. This text applies to the demonstration environment.
      </PageHero>
      <Section tone="white">
        <Doc sections={COOKIES} />
      </Section>
    </>
  );
}
