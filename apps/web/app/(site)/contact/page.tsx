import { Mail } from "lucide-react";
import type { Metadata } from "next";

import { ContentPage, Paragraph } from "@/components/content-page";
import { Link } from "@/components/link";
import { Prose } from "@/components/prose";
import {
  contactFooter,
  contactLead,
  contactRoutes,
  type ContactRoute,
} from "@/lib/content/contact";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

export const metadata: Metadata = pageMetadata({
  title: "Contact",
  description:
    "How to reach makhzan: report a wrong price or product, ask about your shop, ask about your personal data, or write to us about anything else.",
  path: routes.contact(),
});

/**
 * Which way reaches us for what. No form and no endpoint: each route is a
 * link or a `mailto:`, laid out as /for-suppliers' request cards. The copy is
 * lib/content/contact.ts.
 *
 * Fetches nothing, so it stays up when the catalogue does not.
 */
export default function ContactPage() {
  return (
    <ContentPage title="Contact">
      <Paragraph parts={[contactLead]} />
      <div className="mt-8 flex flex-col gap-3">
        {contactRoutes.map((route) => (
          <RouteCard key={route.id} route={route} />
        ))}
      </div>
      <Paragraph parts={contactFooter} className="mt-6" />
    </ContentPage>
  );
}

const BUTTON =
  "inline-flex h-11 shrink-0 items-center justify-center gap-2 self-start rounded-control px-4 text-sm font-semibold whitespace-nowrap sm:self-auto";

function RouteCard({ route }: { route: ContactRoute }) {
  const action = route.action;
  return (
    <section
      data-contact-route={route.id}
      aria-labelledby={`${route.id}-heading`}
      className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4 sm:flex-row sm:items-center sm:gap-5"
    >
      <div className="min-w-0 flex-1">
        <h2 id={`${route.id}-heading`} className="text-base text-ink">
          {route.title}
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">
          <Prose parts={route.body} />
        </p>
      </div>
      {action?.kind === "link" && (
        <Link
          href={action.href}
          className={cn(
            BUTTON,
            action.primary
              ? "bg-action text-action-ink"
              : "border-[1.5px] border-line-strong text-ink hover:bg-ground",
          )}
        >
          {action.label}
        </Link>
      )}
      {action?.kind === "email" && (
        <a
          href={`mailto:${action.email}`}
          aria-label={`${action.label} ${action.email}`}
          className={cn(BUTTON, "border-[1.5px] border-line-strong text-ink hover:bg-ground")}
        >
          <Mail aria-hidden="true" className="size-4" />
          {action.label}
        </a>
      )}
    </section>
  );
}

/** Per request, so its canonical link uses the runtime SITE_URL (as /privacy). */
export const dynamic = "force-dynamic";
