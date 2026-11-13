import { Flag } from "lucide-react";

import { Link } from "@/components/link";
import type { Rich } from "@/lib/content/prose";
import { cn } from "@/lib/utils";

const LINK = "font-semibold text-link hover:underline";

/**
 * One paragraph's worth of copy from lib/content (see lib/content/prose.ts):
 * our own pages through `Link`, a file such as robots.txt and email addresses
 * as plain anchors.
 */
export function Prose({ parts }: { parts: Rich }) {
  return (
    <>
      {parts.map((part, i) => {
        if (typeof part === "string") return <span key={i}>{part}</span>;
        if ("link" in part) {
          return part.href.startsWith("/") && !part.href.includes(".") ? (
            <Link key={i} href={part.href} className={LINK}>
              {part.link}
            </Link>
          ) : (
            <a key={i} href={part.href} className={LINK}>
              {part.link}
            </a>
          );
        }
        if ("email" in part) {
          return (
            <a key={i} href={`mailto:${part.email}`} className={cn(LINK, "break-words")}>
              {part.email}
            </a>
          );
        }
        if ("strong" in part) {
          return (
            <strong key={i} className="font-semibold text-ink">
              {part.strong}
            </strong>
          );
        }
        if ("mono" in part) {
          return (
            <span
              key={i}
              className="font-mono text-[13px] font-medium [overflow-wrap:anywhere] text-ink"
            >
              {part.mono}
            </span>
          );
        }
        return <FlagIllustration key={i} label={part.flag} />;
      })}
    </>
  );
}

/**
 * The "Report a problem" button as it looks beside a product's title, drawn
 * inline so the reader knows what to look for. A picture of the button, not
 * one: there is no product here to report.
 */
export function FlagIllustration({ label }: { label: string }) {
  return (
    <span
      data-flag-illustration
      className="mx-0.5 inline-flex h-[30px] items-center gap-1.5 rounded-control border-[1.5px] border-line-strong px-2.5 align-middle text-[13px] font-semibold whitespace-nowrap text-ink"
    >
      <Flag aria-hidden="true" className="size-3.5 text-ink-2" />
      {label}
    </span>
  );
}
