import { Mail } from "lucide-react";
import type { Metadata } from "next";

import { Link } from "@/components/link";
import { Container } from "@/components/section";
import {
  CONTACT_EMAIL,
  mailtoHref,
  supplierRequests,
  type SupplierRequest,
} from "@/lib/content/supplier-requests";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "For suppliers",
  description:
    "Remove your shop from makhzan, add it, or correct its details. Removal takes at most 7 days, no questions asked.",
  alternates: { canonical: "/for-suppliers" },
};

/**
 * Written for shop owners, who will be emailed and asked whether makhzan may
 * keep listing them (docs/PRODUCT.md). They have to see they can leave before
 * they agree to stay, so leaving comes first and says how fast.
 *
 * Fetches nothing: it is prerendered, and stays up when the catalogue is not.
 */
export default function ForSuppliersPage() {
  const [remove, ...others] = supplierRequests;
  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl sm:text-3xl">For suppliers</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-2">
        makhzan is a free directory of Egyptian hardware and electronics shops. It shows what your
        site already publishes and sends buyers to your own product pages to buy. It sells nothing,
        takes no commission, and no shop pays to appear.
      </p>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-2">
        If you own a shop, you decide whether it is here. Each option below opens an email to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-link hover:underline">
          {CONTACT_EMAIL}
        </a>{" "}
        with the details we need already laid out.
      </p>

      <div className="mt-8 flex flex-col gap-3">
        <RequestCard request={remove} prominent />
        {others.map((request) => (
          <RequestCard key={request.id} request={request} />
        ))}
      </div>

      <section className="mt-10">
        <h2 className="text-lg text-ink">How makhzan reads your site</h2>
        <ul className="mt-3 flex list-disc flex-col gap-1.5 ps-5 text-[15px] leading-relaxed text-ink-2">
          <li>
            Only public catalogue pages, the same ones any visitor sees. No logins, no orders.
          </li>
          <li>Your robots.txt is obeyed, and so is any Crawl-delay you set.</li>
          <li>
            One request at a time, at least 15 seconds apart, spread over about a week. Every
            request names the crawler and this address.
          </li>
          <li>Every price on makhzan says when it was last checked, and links to your page.</li>
        </ul>
        <Link
          href={routes.howWeCrawl()}
          className="mt-3 inline-flex h-11 items-center text-sm font-semibold text-link hover:underline"
        >
          How we crawl, in full
        </Link>
      </section>
    </Container>
  );
}

function RequestCard({
  request,
  prominent = false,
}: {
  request: SupplierRequest;
  prominent?: boolean;
}) {
  return (
    <section
      data-request={request.id}
      className={cn(
        "flex flex-col gap-3 rounded-card border bg-surface p-4 sm:flex-row sm:items-center sm:gap-5",
        prominent ? "border-line-strong" : "border-line",
      )}
    >
      <div className="flex-1">
        <h2 className={cn("text-ink", prominent ? "text-lg" : "text-base")}>{request.title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">{request.summary}</p>
      </div>
      <a
        href={mailtoHref(CONTACT_EMAIL, request)}
        className={cn(
          "inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-control px-4 text-sm font-semibold whitespace-nowrap",
          prominent
            ? "bg-action text-action-ink"
            : "border-[1.5px] border-line-strong text-ink hover:bg-ground",
        )}
      >
        <Mail aria-hidden="true" className="size-4" />
        {request.action}
      </a>
    </section>
  );
}
