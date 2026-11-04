import { PageHero, Section } from "@/components/site/blocks";
import { pageMeta } from "@/lib/seo";
import { Doc } from "../doc";
import { TERMS } from "../text";

export const metadata = pageMeta({
  title: "Terms of use",
  description: "Terms that apply to the demonstration environment.",
  path: "/legal/terms",
});

export default function Page() {
  return (
    <>
      <PageHero eyebrow="Legal" title="Terms of use">
        Last updated 2 November 2026. This text applies to the demonstration environment.
      </PageHero>
      <Section tone="white">
        <Doc sections={TERMS} />
      </Section>
    </>
  );
}
