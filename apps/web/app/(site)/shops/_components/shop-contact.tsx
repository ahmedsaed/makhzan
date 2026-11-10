import { ChevronDown, MapPin, Store } from "lucide-react";
import type { ReactNode } from "react";

import {
  ContactActionsRow,
  ContactLink,
  HoursLine,
  ReportText,
  contactActions,
} from "@/components/contact-links";
import { Dotted, INLINE_LINK } from "@/components/dotted";
import { SectionHeading } from "@/components/section";
import type { ShopBranch, ShopContact } from "@/lib/api";
import {
  addressLine,
  formatPhone,
  provenanceDetails,
  provenanceLine,
  telHref,
} from "@/lib/contact";
import { cn } from "@/lib/utils";

/**
 * How to reach a shop, compact enough to sit under "Visit" in the header's
 * right-hand column on a desktop, and straight under it on a phone:
 *
 *   [Call 02 2345 6789] [WhatsApp] [Email]  or 02 2345 6780
 *   (pin)   12 Example Street, 2nd floor · Open in maps
 *   (store) Giza branch: 3 Other Street, Dokki, Giza · 02 3333 4444 · Open in maps
 *   (clock) Sat–Thu 10:00–22:00 · Fri closed
 *   From Shop A's website and Google Maps, checked 3–8 Nov (v) · Something wrong? Tell us
 *
 * The first number is the button; any others follow as plain links, since a
 * second number is worth a glance but not a button's weight, and hiding it
 * behind a "+1 more" would cost a tap to read eleven digits. The address
 * leaves out the area and governorate the header already shows
 * (`shownPlace`) or that it names itself. The last line opens, as a native
 * <details>, into where each detail came from and when (provenanceDetails).
 * Text is as published, in whatever language, hence `dir="auto"`. Nothing
 * renders for a shop nobody has found anything for; the line at the foot of
 * the page says what is missing.
 */
export function ShopContactSection({
  contact,
  shop,
  shopName,
  websiteUrl,
  page,
  shownPlace = [],
  now,
  className,
}: {
  contact: ShopContact;
  shop: string;
  shopName: string;
  websiteUrl: string | null;
  /** The shop page's absolute URL, for the report email. */
  page: string;
  /** The places the page already names (the header's area and governorate). */
  shownPlace?: (string | null)[];
  /** For the year in "checked 10 Nov": shown only when it is not this year's. */
  now?: Date;
  className?: string;
}) {
  // Every number a "Call …" button like the first: one row of the same buttons.
  const actions = contactActions(
    { phones: contact.phones, whatsapp: contact.whatsapp, email: contact.email },
    shopName,
  );
  const hasBranches = contact.branches.length > 0;
  const mainAddress = addressLine(contact.address, [contact.area, contact.governorate], shownPlace);
  const mainPlace = [contact.area, contact.governorate].filter(Boolean).join(", ");

  const lines: ReactNode[] = [];
  if (mainAddress || contact.maps_url) {
    lines.push(
      <Line key="address" kind="address" icon={<MapPin aria-hidden="true" />}>
        <Dotted>
          {mainAddress && (
            <span>
              {hasBranches && <span className="text-ink-2">Main shop: </span>}
              <span dir="auto">{mainAddress}</span>
            </span>
          )}
          {contact.maps_url && (
            <MapLink
              href={contact.maps_url}
              shop={shop}
              label={`Map: ${shopName}${mainPlace ? `, ${mainPlace}` : ""}`}
            />
          )}
        </Dotted>
      </Line>,
    );
  }
  contact.branches.forEach((branch, index) => {
    lines.push(
      <BranchLine key={`branch-${index}`} branch={branch} shop={shop} shopName={shopName} />,
    );
  });

  const hasHours = contact.opening_hours.length > 0;
  if (actions.length === 0 && lines.length === 0 && !hasHours) {
    return null;
  }
  const source = provenanceLine(contact, shopName, websiteUrl, now);
  const details = provenanceDetails(contact, shopName, websiteUrl);

  return (
    <section
      data-shop-contact
      aria-labelledby="shop-contact-heading"
      className={cn("min-w-0", className)}
    >
      <SectionHeading
        id="shop-contact-heading"
        className="mb-2 lg:font-sans lg:text-[13px] lg:font-semibold lg:text-ink-2"
      >
        Contact
      </SectionHeading>
      {actions.length > 0 && <ContactActionsRow actions={actions} shop={shop} />}
      {(lines.length > 0 || hasHours) && (
        <div className="mt-3 flex flex-col gap-1.5 text-sm leading-snug lg:mt-2.5 lg:gap-1">
          {lines}
          <HoursLine hours={contact.opening_hours} className="text-ink" />
        </div>
      )}
      {/* Phones: the summary and "Tell us" each a real 44px row (S4); an
          invisible extension would overlap the line above and steal its taps. */}
      <Dotted className="mt-1 text-[13px] leading-snug text-ink-2 lg:mt-2">
        {source && (
          <details data-contact-sources className="group">
            <summary
              data-contact-source
              className="flex min-h-11 cursor-pointer list-none items-center hover:text-ink lg:block lg:min-h-0 [&::-webkit-details-marker]:hidden"
            >
              <span>
                {source}
                <ChevronDown
                  aria-hidden="true"
                  className="ms-0.5 inline size-3.5 align-[-2px] transition-transform group-open:rotate-180"
                />
                <span className="sr-only"> (sources)</span>
              </span>
            </summary>
            {details.length > 0 && (
              <ul className="my-1.5 flex flex-col gap-0.5 border-s-2 border-line ps-2.5">
                {details.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </details>
        )}
        <ReportText shop={shop} shopName={shopName} page={page} />
      </Dotted>
    </section>
  );
}

/** One line of the block: an icon, then the text, wrapping under itself. */
function Line({ kind, icon, children }: { kind: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div data-contact-line={kind} className="flex gap-2 text-ink">
      <span className="mt-[3px] shrink-0 text-ink-2 [&>svg]:size-3.5">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function MapLink({ href, shop, label }: { href: string; shop: string; label: string }) {
  return (
    <ContactLink
      kind="map"
      shop={shop}
      href={href}
      aria-label={label}
      className={cn(INLINE_LINK, "whitespace-nowrap")}
    >
      Open in maps
    </ContactLink>
  );
}

function PhoneText({ number, shop, shopName }: { number: string; shop: string; shopName: string }) {
  const href = telHref(number);
  const text = formatPhone(number);
  if (!href) return <span className="text-ink tabular">{text}</span>;
  return (
    <ContactLink
      kind="phone"
      shop={shop}
      href={href}
      aria-label={`Call ${shopName} on ${text}`}
      className={cn(INLINE_LINK, "whitespace-nowrap")}
    >
      <span className="tabular">{text}</span>
    </ContactLink>
  );
}

/** "Giza branch: 3 Other Street, Dokki, Giza · 02 3333 4444 · Open in maps". */
function BranchLine({
  branch,
  shop,
  shopName,
}: {
  branch: ShopBranch;
  shop: string;
  shopName: string;
}) {
  const place = [branch.area, branch.governorate].filter(Boolean).join(", ");
  const address = addressLine(branch.address, [branch.area, branch.governorate], [branch.name]);
  // "Call Shop A Giza branch on …": which of the shop's places the number rings.
  const label = branch.name ? `${shopName} ${branch.name}` : shopName;
  return (
    <Line kind="branch" icon={<Store aria-hidden="true" />}>
      <Dotted>
        <span>
          <span dir="auto" className="text-ink-2">
            {branch.name ?? "Branch"}:{" "}
          </span>
          {address && <span dir="auto">{address}</span>}
        </span>
        {branch.phones.map((number) => (
          <PhoneText key={number} number={number} shop={shop} shopName={label} />
        ))}
        {branch.maps_url && (
          <MapLink
            href={branch.maps_url}
            shop={shop}
            label={`Map: ${label}${place ? `, ${place}` : ""}`}
          />
        )}
      </Dotted>
    </Line>
  );
}
