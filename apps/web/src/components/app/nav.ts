import {
  BarChart3,
  Bell,
  BookOpen,
  CreditCard,
  Database,
  FileText,
  Globe2,
  LayoutDashboard,
  type LucideIcon,
  MapPin,
  Newspaper,
  Radar,
  Settings,
  Shapes,
  Shield,
  TrendingUp,
} from "lucide-react";
import { atLeast, isPlatform, type Role } from "@/lib/app/session";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shortcut after "g" */
  key?: string;
  allow: (role: Role) => boolean;
};

const tenant = (role: Role) => !isPlatform(role);

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Monitor",
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboard, key: "o", allow: tenant },
      { href: "/app/map", label: "Map", icon: Globe2, key: "m", allow: tenant },
      { href: "/app/incidents", label: "Incidents", icon: Radar, key: "i", allow: tenant },
      { href: "/app/alerts", label: "Alerts", icon: Bell, key: "a", allow: tenant },
    ],
  },
  {
    label: "Portfolio",
    items: [
      { href: "/app/assets", label: "Assets", icon: MapPin, key: "s", allow: tenant },
      {
        href: "/app/zones",
        label: "Watch zones",
        icon: Shapes,
        key: "z",
        allow: (r) => atLeast(r, "analyst"),
      },
    ],
  },
  {
    label: "Insight",
    items: [
      { href: "/app/briefings", label: "Briefings", icon: Newspaper, key: "b", allow: tenant },
      {
        href: "/app/reports",
        label: "Reports",
        icon: FileText,
        key: "r",
        allow: (r) => atLeast(r, "manager"),
      },
      {
        href: "/app/analytics",
        label: "Analytics",
        icon: BarChart3,
        key: "n",
        allow: (r) => atLeast(r, "manager"),
      },
      {
        href: "/app/sources",
        label: "Data sources",
        icon: Database,
        key: "d",
        allow: (r) => atLeast(r, "manager"),
      },
    ],
  },
  {
    label: "Organisation",
    items: [
      { href: "/app/billing", label: "Billing", icon: CreditCard, allow: (r) => atLeast(r, "tenant_admin") },
      { href: "/app/admin", label: "Administration", icon: Shield, allow: (r) => atLeast(r, "tenant_admin") },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/app/platform/revenue", label: "Revenue", icon: TrendingUp, allow: isPlatform },
      {
        href: "/app/platform/analytics",
        label: "Pipeline analytics",
        icon: BookOpen,
        allow: (r) => r === "platform_admin",
      },
    ],
  },
  {
    label: "Account",
    items: [{ href: "/app/settings", label: "Settings", icon: Settings, key: "e", allow: () => true }],
  },
];

/** First page a role should land on. */
export const homeFor = (role: Role) => (isPlatform(role) ? "/app/platform/revenue" : "/app");

/** Routes and the lowest role that may open them, for route guards. */
export function allowedPath(pathname: string, role: Role): boolean {
  const items = NAV_GROUPS.flatMap((g) => g.items).filter((i) => i.href !== "/app");
  const match = items
    .filter((i) => pathname === i.href || pathname.startsWith(`${i.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0];
  if (pathname === "/app") return tenant(role);
  return match ? match.allow(role) : true;
}
