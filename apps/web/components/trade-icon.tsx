import { createElement } from "react";
import {
  Car,
  CircleDot,
  Cpu,
  Factory,
  FlaskConical,
  Flame,
  HardHat,
  Layers,
  LockKeyhole,
  Package,
  Sprout,
  SprayCan,
  TreePine,
  Waypoints,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

/**
 * A line icon per trade: what an object tile shows until its photo is curated
 * (lib/content/category-images.ts). Neutral on purpose — a stand-in should not
 * look like a product photo.
 */
const ICONS: Record<string, LucideIcon> = {
  automotive: Car,
  chemicals: FlaskConical,
  cleaning: SprayCan,
  electrical: Zap,
  electronics: Cpu,
  garden: Sprout,
  machinery: Factory,
  materials: Layers,
  piping: Waypoints,
  rigging: CircleDot,
  safety: HardHat,
  "seals-bearings": CircleDot,
  security: LockKeyhole,
  timber: TreePine,
  tools: Wrench,
  welding: Flame,
};

export function tradeIcon(domain: string): LucideIcon {
  return ICONS[domain] ?? Package;
}

/** The trade's icon as an element, for markup that is not an ObjectTile. */
export function TradeIcon({ domain, className }: { domain: string; className?: string }) {
  return createElement(tradeIcon(domain), {
    "aria-hidden": true,
    strokeWidth: 1.25,
    className,
  });
}
