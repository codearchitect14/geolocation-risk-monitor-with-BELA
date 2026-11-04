import { Suspense } from "react";
import { PageHero, Section } from "@/components/site/blocks";
import { pageMeta } from "@/lib/seo";
import { DemoForm } from "./demo-form";

export const metadata = pageMeta({
  title: "Request a demo",
  description: "Tell us about your sites and teams and we will arrange a demonstration.",
  path: "/contact",
});

export default function ContactPage() {
  return (
    <>
      <PageHero eyebrow="Contact" title="Request a demo">
        Tell us about your network. We will reply to the work email you provide. The form is also the way to
        ask a question, report a security concern or request a correction.
      </PageHero>
      <Section tone="white">
        <div className="mx-auto max-w-2xl">
          <Suspense fallback={<div className="min-h-[760px] sm:min-h-[600px]" aria-hidden="true" />}>
            <DemoForm />
          </Suspense>
        </div>
      </Section>
    </>
  );
}
