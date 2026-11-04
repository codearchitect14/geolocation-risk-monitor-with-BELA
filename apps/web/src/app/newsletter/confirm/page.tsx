import { Suspense } from "react";
import { PageHero, Section } from "@/components/site/blocks";
import { Confirm } from "./confirm";

export const metadata = { title: "Confirm subscription", robots: { index: false, follow: false } };

export default function Page() {
  return (
    <>
      <PageHero title="Confirm your subscription" />
      <Section tone="white">
        <div className="mx-auto max-w-xl">
          <Suspense>
            <Confirm />
          </Suspense>
        </div>
      </Section>
    </>
  );
}
