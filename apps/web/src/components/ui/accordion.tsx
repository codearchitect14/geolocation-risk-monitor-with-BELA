"use client";

import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type FaqItem = { q: string; a: string };

export function Faq({ items, className }: { items: FaqItem[]; className?: string }) {
  return (
    <AccordionPrimitive.Root
      type="single"
      collapsible
      className={cn("divide-y divide-line rounded-card border border-line bg-white", className)}
    >
      {items.map((item, i) => (
        <AccordionPrimitive.Item key={item.q} value={`item-${i}`}>
          <AccordionPrimitive.Header>
            <AccordionPrimitive.Trigger className="group flex w-full items-center justify-between gap-4 px-5 py-4 text-left font-medium text-ink">
              {item.q}
              <ChevronDown
                className="size-5 shrink-0 text-slate-500 transition-transform duration-200 group-data-[state=open]:rotate-180"
                aria-hidden="true"
              />
            </AccordionPrimitive.Trigger>
          </AccordionPrimitive.Header>
          <AccordionPrimitive.Content className="overflow-hidden px-5 text-slate-700 data-[state=closed]:hidden">
            <p className="pb-5">{item.a}</p>
          </AccordionPrimitive.Content>
        </AccordionPrimitive.Item>
      ))}
    </AccordionPrimitive.Root>
  );
}
