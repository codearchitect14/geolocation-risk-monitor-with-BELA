import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({
  className,
  hover = false,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { hover?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-card border border-line bg-white p-6 shadow-e1",
        hover &&
          "transition-[transform,box-shadow] duration-200 ease-out hover:-translate-y-0.5 hover:shadow-e2",
        className,
      )}
      {...props}
    />
  );
}
