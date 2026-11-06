import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/app/shell";

export const metadata: Metadata = {
  title: { default: "Application", template: "%s | Meridian Signal" },
  robots: { index: false },
};

export default function Layout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
