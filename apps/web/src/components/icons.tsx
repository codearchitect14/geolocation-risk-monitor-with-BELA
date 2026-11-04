import {
  BellRing,
  Braces,
  Container,
  FileSearch,
  Layers,
  MapPin,
  Plane,
  Rss,
  ShieldCheck,
  Siren,
  Tags,
  Target,
  type LucideIcon,
} from "lucide-react";

const icons: Record<string, LucideIcon> = {
  BellRing,
  Braces,
  Container,
  FileSearch,
  Layers,
  MapPin,
  Plane,
  Rss,
  ShieldCheck,
  Siren,
  Tags,
  Target,
};

export function Icon({ name, className }: { name: string; className?: string }) {
  const Component = icons[name] ?? MapPin;
  return <Component className={className} aria-hidden="true" />;
}
