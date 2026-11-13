/**
 * "Report a problem": what the form asks, what it checks, and what it sends.
 *
 * Pure, so every rule is tested without a browser (tests/report.test.ts); the
 * dialog (components/report-problem.tsx) only draws the state kept here. The
 * API checks the same things again (apps/api/app/routers/reports.py) and holds
 * the spam rules and the limits; what is kept, and for how long, is the
 * privacy page's (lib/content/privacy.ts), and the note under the form says it
 * in short.
 */
import type { Offer } from "@/lib/api";
import { CONTACT_EMAIL } from "@/lib/content/crawling";
import { mailtoHref } from "@/lib/content/supplier-requests";
import { formatPrice, NO_PRICE, PRICE_ON_REQUEST } from "@/lib/format";
import { isOnRequest, isOutOfStock, isStaleOffer } from "@/lib/offers";
import { splitOffers } from "@/lib/product";
import { productIdFrom } from "@/lib/routes";

export type ReasonKey =
  | "offers_not_same"
  | "same_as_other"
  | "wrong_price_stock"
  | "wrong_category"
  | "wrong_details"
  | "shop_contact"
  | "other";

export type Reason = {
  key: ReasonKey;
  title: string;
  hint?: string;
  /** Only where there is more than one offer to compare. */
  severalOnly?: boolean;
};

export const REASONS: readonly Reason[] = [
  {
    key: "offers_not_same",
    title: "These offers aren’t the same product",
    hint: "One or more shops sell something different",
    severalOnly: true,
  },
  {
    key: "same_as_other",
    title: "This is the same as another product",
    hint: "It’s listed twice on makhzan",
  },
  {
    key: "wrong_price_stock",
    title: "Wrong price or stock",
    hint: "The shop’s site says something different",
  },
  { key: "wrong_category", title: "Wrong category", hint: "It’s filed in the wrong place" },
  { key: "wrong_details", title: "Wrong details", hint: "Title, specifications or photo" },
  {
    key: "shop_contact",
    title: "A shop’s contact details are wrong",
    hint: "Phone, WhatsApp, opening hours or address",
  },
  { key: "other", title: "Something else" },
];

export const PRICE_FIELDS = [
  ["price", "The price"],
  ["stock", "The stock"],
] as const;
export const STOCK_VALUES = [
  ["in_stock", "In stock"],
  ["out_of_stock", "Out of stock"],
  ["gone", "No longer listed"],
] as const;
export const DETAIL_FIELDS = [
  ["title", "Title"],
  ["specs", "Specifications"],
  ["photo", "Photo"],
  ["description", "Description"],
] as const;
export const CONTACT_FIELDS = [
  ["phone", "Phone"],
  ["whatsapp", "WhatsApp"],
  ["hours", "Opening hours"],
  ["address", "Address"],
] as const;

export type PriceField = (typeof PRICE_FIELDS)[number][0];
export type StockValue = (typeof STOCK_VALUES)[number][0];
export type DetailField = (typeof DETAIL_FIELDS)[number][0];
export type ContactField = (typeof CONTACT_FIELDS)[number][0];

/** The limits the API enforces, so the form can say them before it is refused. */
export const MAX_DESCRIPTION = 1000;
/** Kept in step with makhzan_schemas/reports.py and the privacy page. */
export const EMAIL_KEPT_DAYS = 90;
export const IP_HASH_KEPT_HOURS = 24;

/** One offer as the form lists it: the shop's own title, its shop, its price. */
export type ReportOffer = {
  id: string;
  title: string;
  shop: { slug: string; name: string } | null;
  /** "EGP 425", "EGP 550 – 620", "Price on request". */
  price: string;
  outOfStock: boolean;
  /** Not checked in over 45 days (C2b). */
  stale: boolean;
};

/** What the page knows that the form needs. Built on the server. */
export type ReportContext = {
  productId: string;
  title: string;
  /** Every offer, folded ones included, in the page's order. */
  offers: ReportOffer[];
  /** "Electronic components › Motor control › Stepper drivers", or null. */
  category: string | null;
  /** The page's absolute URL, for the email fallback. */
  page: string;
};

/**
 * The form's view of a product page: every offer in the page's own order
 * (listed, then out of stock, then out of date), each with its own title,
 * shop and price, so a visitor recognises the row they mean.
 */
export function reportContextOf({
  productId,
  title,
  offers,
  category,
  page,
  now,
}: {
  productId: string;
  title: string;
  offers: Offer[];
  category: string | null;
  page: string;
  now: Date;
}): ReportContext {
  const { listed, outOfStock, stale } =
    offers.length > 1 ? splitOffers(offers, now) : { listed: offers, outOfStock: [], stale: [] };
  return {
    productId,
    title,
    category,
    page,
    offers: [...listed, ...outOfStock, ...stale].map((offer) => ({
      id: offer.id,
      title: offer.title_en || offer.title_ar || title,
      shop: offer.supplier ? { slug: offer.supplier.slug, name: offer.supplier.name } : null,
      price:
        offer.price !== null
          ? formatPrice(offer.price, offer.currency)
          : isOnRequest(offer)
            ? PRICE_ON_REQUEST
            : NO_PRICE,
      outOfStock: isOutOfStock(offer),
      stale: isStaleOffer(offer, now),
    })),
  };
}

/** The other product, for "the same as another product". */
export type PickedProduct = { id: string; title: string; meta: string; partNumber?: string | null };

export type FormState = {
  step: 1 | 2;
  reason: ReasonKey | null;
  offers: string[];
  other: PickedProduct | null;
  priceOffer: string | null;
  field: PriceField | null;
  value: string;
  stockValue: StockValue | null;
  category: string;
  detailField: DetailField | null;
  detailShop: string;
  contactShop: string;
  contactField: ContactField | null;
  description: string;
  email: string;
  /** The honeypot. Filled only by something that is not a person. */
  website: string;
};

export function blankForm(): FormState {
  return {
    step: 1,
    reason: null,
    offers: [],
    other: null,
    priceOffer: null,
    field: null,
    value: "",
    stockValue: null,
    category: "",
    detailField: null,
    detailShop: "",
    contactShop: "",
    contactField: null,
    description: "",
    email: "",
    website: "",
  };
}

export function several(context: ReportContext): boolean {
  return context.offers.length > 1;
}

/** The reasons this product can be reported for: comparing offers needs two. */
export function reasonsFor(context: ReportContext): Reason[] {
  return REASONS.filter((reason) => !reason.severalOnly || several(context));
}

export function reasonOf(key: ReasonKey | null): Reason | null {
  return REASONS.find((reason) => reason.key === key) ?? null;
}

/** Each shop once, in the offers' order. */
export function shopsOf(context: ReportContext): { slug: string; name: string }[] {
  const seen = new Map<string, { slug: string; name: string }>();
  for (const offer of context.offers) {
    if (offer.shop && !seen.has(offer.shop.slug)) seen.set(offer.shop.slug, offer.shop);
  }
  return [...seen.values()];
}

export type FieldErrors = Partial<
  Record<
    | "reason"
    | "offers"
    | "other"
    | "priceOffer"
    | "field"
    | "detailField"
    | "contactShop"
    | "contactField"
    | "description"
    | "email",
    string
  >
>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** What stops the current step, in the order the fields appear. */
export function validate(state: FormState, context: ReportContext): FieldErrors {
  const errors: FieldErrors = {};
  if (state.step === 1) {
    if (!state.reason) errors.reason = "Choose what’s wrong to continue.";
    return errors;
  }
  const many = several(context);
  switch (state.reason) {
    case "offers_not_same":
      if (state.offers.length === 0)
        errors.offers = "Tick at least one offer that is a different product.";
      break;
    case "same_as_other":
      if (!state.other) errors.other = "Pick the other product, or paste its makhzan link.";
      break;
    case "wrong_price_stock":
      if (many && !state.priceOffer) errors.priceOffer = "Choose the offer that’s wrong.";
      if (!state.field) errors.field = "Choose price or stock.";
      break;
    case "wrong_details":
      if (!state.detailField) errors.detailField = "Choose what’s wrong.";
      break;
    case "shop_contact":
      if (many && shopsOf(context).length > 1 && !state.contactShop)
        errors.contactShop = "Choose the shop.";
      if (!state.contactField) errors.contactField = "Choose which detail.";
      break;
    case "other":
      if (state.description.trim().length < 5)
        errors.description = "Tell us what’s wrong, in a few words.";
      break;
  }
  if (state.description.length > MAX_DESCRIPTION)
    errors.description = `Keep it under ${MAX_DESCRIPTION.toLocaleString("en-US")} characters.`;
  const email = state.email.trim();
  if (email && !EMAIL.test(email))
    errors.email = "That email doesn’t look complete. Leave it empty if you prefer.";
  return errors;
}

/** "460" or "EGP 1,200.50" as the visitor typed it, as "EGP 460"; null for nothing usable. */
export function priceValue(typed: string): string | null {
  const digits = typed
    .replace(/egp|le|ج\.?م/gi, "")
    .replace(/[\s,]/g, "")
    .trim();
  if (!/^\d+(\.\d{1,2})?$/.test(digits)) return null;
  const [whole, cents] = digits.split(".");
  const grouped = Number(whole).toLocaleString("en-US");
  return `EGP ${grouped}${cents ? `.${cents}` : ""}`;
}

export type ReportPayload = {
  product_id: string;
  reason: ReasonKey;
  offer_ids: string[];
  other_product_id: string | null;
  field: string | null;
  correct_value: string | null;
  description: string | null;
  email: string | null;
  website: string;
  elapsed_ms: number;
};

/** The body of `POST /reports`: only what the chosen reason takes. */
export function buildPayload(
  state: FormState,
  context: ReportContext,
  elapsedMs: number,
): ReportPayload {
  const reason = state.reason ?? "other";
  const many = several(context);
  const offersOfShop = (slug: string) =>
    context.offers.filter((offer) => offer.shop?.slug === slug).map((offer) => offer.id);
  const shops = shopsOf(context);
  let offerIds: string[] = [];
  let field: string | null = null;
  let correct: string | null = null;
  switch (reason) {
    case "offers_not_same":
      offerIds = [...state.offers];
      break;
    case "wrong_price_stock": {
      const id = many ? state.priceOffer : (context.offers[0]?.id ?? null);
      offerIds = id ? [id] : [];
      field = state.field;
      correct =
        state.field === "price"
          ? priceValue(state.value)
          : state.field === "stock"
            ? state.stockValue
            : null;
      break;
    }
    case "wrong_category":
      field = "category";
      correct = state.category.trim() || null;
      break;
    case "wrong_details":
      field = state.detailField;
      {
        // With one shop there is no choice to make: its text is the only text.
        const slug = shops.length === 1 ? shops[0].slug : state.detailShop;
        offerIds = slug ? offersOfShop(slug) : [];
      }
      break;
    case "shop_contact": {
      field = state.contactField;
      const slug = shops.length === 1 ? shops[0].slug : state.contactShop;
      offerIds = slug ? offersOfShop(slug) : [];
      break;
    }
  }
  return {
    product_id: context.productId,
    reason,
    offer_ids: offerIds,
    other_product_id: reason === "same_as_other" ? (state.other?.id ?? null) : null,
    field,
    correct_value: correct,
    description: state.description.trim() || null,
    email: state.email.trim() || null,
    website: state.website,
    elapsed_ms: Math.max(0, Math.round(elapsedMs)),
  };
}

/** A makhzan product link, or a bare id, pasted into the search box: its id, else null. */
export function productIdFromLink(text: string): string | null {
  const value = text.trim();
  const path = value.match(/\/products\/([^/?#\s]+)/);
  if (path) return productIdFrom(path[1]);
  const uuid = value.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  return uuid ? value.toLowerCase() : null;
}

/** "Sold by 1 shop · EGP 390", "3 shops · EGP 900 – 990": a candidate's line in the list. */
export function candidateMeta(
  shops: number,
  price: string | null,
  shopName?: string | null,
): string {
  const who =
    shops > 1 ? `${shops} shops` : shopName ? `Sold by ${shopName}` : `Sold by ${shops} shop`;
  return price ? `${who} · ${price}` : who;
}

export type Limited = { limit: "hour" | "day"; count: number; minutes: number };

export type SubmitResult =
  { kind: "sent"; reference: string | null } | ({ kind: "limited" } & Limited) | { kind: "error" };

/** "about 40 minutes", "about 3 hours". */
export function waitText(minutes: number): string {
  if (minutes < 90) {
    const m = Math.max(1, Math.round(minutes));
    return `about ${m} minute${m === 1 ? "" : "s"}`;
  }
  const hours = Math.round(minutes / 60);
  return `about ${hours} hours`;
}

/** The headline of the "too many reports" state. */
export function limitedTitle(limited: Limited): string {
  return limited.limit === "hour"
    ? `You’ve sent ${limited.count} reports in the last hour.`
    : `You’ve sent ${limited.count} reports in the last day.`;
}

/** Where the browser reaches the API: same origin, through the web app's rewrite. */
export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "/api";
}

/** Send a report. Never throws: a failure is a state the form shows. */
export async function submitReport(
  payload: ReportPayload,
  fetcher: typeof fetch = fetch,
): Promise<SubmitResult> {
  try {
    const response = await fetcher(`${apiBase()}/reports`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.status === 429) {
      const body = await response.json().catch(() => null);
      const detail = body?.detail ?? {};
      const retry = Number(response.headers.get("retry-after"));
      return {
        kind: "limited",
        limit: detail.limit === "day" ? "day" : "hour",
        count: Number(detail.count) || (detail.limit === "day" ? 20 : 5),
        minutes:
          Number(detail.retry_after_minutes) ||
          (Number.isFinite(retry) && retry > 0 ? Math.ceil(retry / 60) : 60),
      };
    }
    if (!response.ok) return { kind: "error" };
    const body = await response.json().catch(() => null);
    return { kind: "sent", reference: typeof body?.reference === "string" ? body.reference : null };
  } catch {
    return { kind: "error" };
  }
}

/** The fallback when the form cannot send: an email carrying what was written. */
export function emailFallback(state: FormState, context: ReportContext): string {
  const reason = reasonOf(state.reason);
  return mailtoHref(CONTACT_EMAIL, {
    subject: `Report a problem: ${context.title}`,
    body: [
      reason ? `What's wrong: ${reason.title.replace("’", "'")}` : "What's wrong:",
      "",
      state.description.trim(),
      "",
      "---",
      `Page: ${context.page}`,
    ].join("\n"),
  });
}
