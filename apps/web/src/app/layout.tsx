import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import { SiteShell } from "@/components/site/shell";
import { BRAND, SITE_URL } from "@/lib/utils";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: `${BRAND}: operational disruption intelligence`, template: `%s | ${BRAND}` },
  description:
    "Entity-aware monitoring links news and public hazard feeds to the places and assets that matter to you.",
  openGraph: { siteName: BRAND, type: "website", locale: "en_US" },
  twitter: { card: "summary_large_image" },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = { themeColor: "#0B1B33", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteShell>{children}</SiteShell>
      </body>
    </html>
  );
}
