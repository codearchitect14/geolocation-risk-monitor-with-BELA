"use client";

import { ProductMock } from "@/components/art/product-mock";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  {
    id: "map",
    label: "Live map",
    caption:
      "Incidents are drawn with a shape and a size for each level, so the map can be read without color.",
  },
  {
    id: "exposure",
    label: "Asset exposure",
    caption: "Assets are listed by exposure level and distance, with the location uncertainty beside each.",
  },
  {
    id: "incident",
    label: "Incident detail",
    caption:
      "Sources, the located places and the timeline are on one page, so a person can check the evidence.",
  },
  {
    id: "analytics",
    label: "Analytics",
    caption: "Incident volumes, alert levels and acknowledgement time over the period you choose.",
  },
] as const;

export function ProductTabs() {
  return (
    <Tabs defaultValue="map">
      <TabsList aria-label="Product views">
        {TABS.map((t) => (
          <TabsTrigger key={t.id} value={t.id}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {TABS.map((t) => (
        <TabsContent key={t.id} value={t.id} className="mt-6">
          <ProductMock tab={t.id} />
          <p className="mt-3 text-small text-slate-700">
            {t.caption} <span className="text-slate-600">Illustrative interface rendering.</span>
          </p>
        </TabsContent>
      ))}
    </Tabs>
  );
}
