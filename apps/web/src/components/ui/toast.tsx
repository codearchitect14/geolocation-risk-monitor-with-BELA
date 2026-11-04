"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type Toast = { id: number; message: string; tone: "info" | "error" };
const ToastContext = React.createContext<(message: string, tone?: Toast["tone"]) => void>(() => undefined);
export const useToast = () => React.useContext(ToastContext);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const push = React.useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "rounded-control border bg-white px-4 py-3 text-small shadow-e3",
              t.tone === "error" ? "border-danger text-danger" : "border-line text-ink",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
