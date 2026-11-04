import { PageHero, Section } from "@/components/site/blocks";
import { pageMeta } from "@/lib/seo";
import { Doc } from "../doc";
import { PRIVACY } from "../text";

export const metadata = pageMeta({
  title: "Privacy policy",
  description: "How the demonstration environment collects, uses and protects personal data.",
  path: "/legal/privacy",
});

export default function Page() {
  return (
    <>
      <PageHero eyebrow="Legal" title="Privacy policy">
        Last updated 2 November 2026. This text applies to the demonstration environment.
      </PageHero>
      <Section tone="white">
        <Doc sections={PRIVACY} />
      </Section>
    </>
  );
}
