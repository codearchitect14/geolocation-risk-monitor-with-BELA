"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

/** Centered dialog, or a side drawer when `side` is set. */
export function DialogContent({
  className,
  children,
  side,
  closeLabel = "Close",
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: "right" | "left"; closeLabel?: string }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/50 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 bg-white shadow-e3 focus:outline-none",
          side
            ? cn("inset-y-0 w-[88vw] max-w-sm overflow-y-auto p-6", side === "right" ? "right-0" : "left-0")
            : "left-1/2 top-1/2 w-[92vw] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-card p-6",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute right-4 top-4 rounded-md p-1 text-slate-600 hover:bg-slate-100"
          aria-label={closeLabel}
        >
          <X className="size-5" aria-hidden="true" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
