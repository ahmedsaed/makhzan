"use client";

import { Check, Eye } from "lucide-react";
import {
  createContext,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

const noop = () => () => {};

import { PhotoFrame } from "@/components/photo-frame";
import type { GalleryPhoto } from "@/lib/product";
import { openOffersReport } from "@/lib/report";
import { aiNoteText, shopViewUrl } from "@/lib/shop-view";
import { cn } from "@/lib/utils";

import { jumpStrip } from "./carousel";

/**
 * The shop view (lib/shop-view.ts): which offer is picked, and the pieces of
 * the page that follow it. The server renders every piece in the picked
 * state it chose (the cheapest offer, or `?shop=`'s), so the page is complete
 * without JavaScript; picking another shop here swaps them in place and
 * rewrites `?shop=` with replaceState, adding nothing to the history.
 */

/** What the page needs to know about each offer to follow it. */
export type PickMeta = {
  /** Its shop's slug, for `?shop=`; null for an offer with no shop. */
  slug: string | null;
  shop: string;
  /** The shop's own title, for the h1. */
  title: string;
  /** Has a link out, so the button and the bar can open it. */
  linkable: boolean;
  /** Its shop's first photo in the gallery, if any. */
  photo: number | null;
  /** Its shop's "What the shops say" tab, if any. */
  detail: number | null;
};

type ShopView = {
  picked: string;
  /** The offer the primary button and the bottom bar open: the picked one
   *  when it has a link out, else the primary offer. */
  action: string | null;
  /** The open "What the shops say" tab. */
  detail: number;
  /** The gallery photo the page shows. */
  photo: number;
  /** Picks the visitor has made: 0 until the first. */
  picks: number;
  meta: Readonly<Record<string, PickMeta>>;
  pick: (offerId: string) => void;
};

const ShopViewContext = createContext<ShopView | null>(null);

export function ShopViewProvider({
  initial,
  explicit,
  primary,
  meta,
  children,
}: {
  /** The offer picked on load. */
  initial: string;
  /** Picked by `?shop=` rather than by price: the gallery opens on its photo. */
  explicit: boolean;
  primary: string | null;
  meta: Record<string, PickMeta>;
  children: ReactNode;
}) {
  const start = meta[initial];
  const [picked, setPicked] = useState(initial);
  const [detail, setDetail] = useState(start?.detail ?? 0);
  // On a plain load the gallery stays on the product's own first photo, as
  // before the shop view (it is the page's largest paint); a linked shop view
  // opens on that shop's.
  const [photo, setPhoto] = useState(explicit ? (start?.photo ?? 0) : 0);
  const [picks, setPicks] = useState(0);

  const pick = useCallback(
    (offerId: string) => {
      const next = meta[offerId];
      if (!next) return;
      setPicked(offerId);
      if (next.detail !== null) setDetail(next.detail);
      if (next.photo !== null) setPhoto(next.photo);
      setPicks((count) => count + 1);
      // A row folded away (out of stock, out of date) opens, so the highlight
      // is seen.
      const row = document.querySelector(`[data-offer="${CSS.escape(offerId)}"]`);
      const fold = row?.closest("details");
      if (fold) fold.open = true;
      if (next.slug) {
        try {
          window.history.replaceState(null, "", shopViewUrl(window.location.href, next.slug));
        } catch {
          // A sandboxed frame may refuse; the view has switched either way.
        }
      }
    },
    [meta],
  );

  const value = useMemo<ShopView>(
    () => ({
      picked,
      action: meta[picked]?.linkable ? picked : primary,
      detail,
      photo,
      picks,
      meta,
      pick,
    }),
    [picked, primary, detail, photo, picks, meta, pick],
  );
  return <ShopViewContext.Provider value={value}>{children}</ShopViewContext.Provider>;
}

export function useShopView(): ShopView | null {
  return useContext(ShopViewContext);
}

/** The page's h1: the picked shop's own title for its listing. */
export function ShopTitle({ fallback, className }: { fallback: string; className?: string }) {
  const view = useShopView();
  const current = view ? view.meta[view.picked] : undefined;
  return (
    <h1 dir="auto" data-shop-title={current?.slug ?? undefined} className={className}>
      {current?.title || fallback}
    </h1>
  );
}

/** Its children only while `offer` is the one the button and bar open. */
export function WhenAction({ offer, children }: { offer: string; children: ReactNode }) {
  const view = useShopView();
  return view && view.action !== offer ? null : <>{children}</>;
}

/**
 * An offer's row, ringed while its offer is picked: an inset 2px ring in the
 * `link` colour on the `ground` fill, no new token.
 */
export function OfferRowShell({
  offer,
  className,
  children,
}: {
  offer: string;
  className?: string;
  children: ReactNode;
}) {
  const view = useShopView();
  const picked = view?.picked === offer;
  return (
    <li
      data-offer={offer}
      data-picked={picked ? "" : undefined}
      aria-current={picked ? "true" : undefined}
      className={cn(className, picked && "bg-ground ring-2 ring-link ring-inset")}
    >
      {children}
    </li>
  );
}

/**
 * "View listing" on a row: shows that shop's listing on this page. A link to
 * `?shop=`, so without JavaScript it still opens the shop's view (as a page
 * load); with it, the view switches in place. The picked row says so instead.
 */
export function ViewListing({ offer, slug, shop }: { offer: string; slug: string; shop: string }) {
  const view = useShopView();
  if (view?.picked === offer) {
    return (
      <span
        data-showing-listing
        className="inline-flex min-h-11 items-center gap-1 text-[13px] font-medium text-ink lg:min-h-9"
      >
        <Check aria-hidden="true" className="size-3.5 text-link" />
        Showing this listing
      </span>
    );
  }
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!view || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    view.pick(offer);
  };
  return (
    <a
      href={`?${new URLSearchParams({ shop: slug })}`}
      onClick={onClick}
      data-view-listing
      aria-label={`View ${shop}’s listing on this page`}
      className="inline-flex min-h-11 items-center gap-1 rounded-control text-[13px] font-semibold text-link outline-offset-2 outline-link hover:underline focus-visible:outline-2 lg:min-h-9"
    >
      <Eye aria-hidden="true" className="size-3.5" />
      View listing
    </a>
  );
}

/**
 * A "What the shops say" tab's radio. Checked by the shop view (the server
 * renders the picked shop's tab checked, so the CSS shows its panel without
 * JavaScript); choosing a tab picks its shop. A click counts even on the open
 * tab, which picks it when the picked shop has no tab of its own.
 */
export function PickerRadio({
  index,
  offer,
  label,
  className,
}: {
  index: number;
  offer: string;
  /** Its accessible name, when the label's text is not all of it. */
  label?: string;
  className?: string;
}) {
  const view = useShopView();
  const id = `details-source-${index}`;
  if (!view) {
    return (
      <input
        type="radio"
        name="details-source"
        id={id}
        defaultChecked={index === 0}
        aria-label={label}
        className={className}
      />
    );
  }
  const choose = () => view.pick(offer);
  return (
    <input
      type="radio"
      name="details-source"
      id={id}
      checked={view.detail === index}
      onChange={choose}
      onClick={choose}
      aria-label={label}
      className={className}
    />
  );
}

/**
 * Moves the gallery strip beside it to the picked shop's photo: gliding, or
 * at once when motion is reduced, and at once on load for a linked shop view.
 */
export function GalleryFollower() {
  const view = useShopView();
  const anchor = useRef<HTMLSpanElement>(null);
  const photo = view?.photo ?? 0;
  const picks = view?.picks ?? 0;
  useEffect(() => {
    const track = anchor.current?.parentElement?.querySelector<HTMLElement>("[data-gallery]");
    if (!track) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    // On load, only a linked view has anywhere to go (photo > 0); then no glide.
    if (picks === 0 && photo === 0) return;
    jumpStrip(track, photo, picks > 0 && !reduced);
  }, [photo, picks]);
  return <span ref={anchor} hidden />;
}

/** The phone's thumbnail beside the title, showing the photo the view shows. */
export function PickedThumb({
  photos,
  alt,
  className,
}: {
  photos: GalleryPhoto[];
  alt: string;
  className?: string;
}) {
  const view = useShopView();
  const shown = photos[view?.photo ?? 0] ?? photos[0];
  return (
    <PhotoFrame
      src={shown?.src ?? null}
      shop={shown?.shop}
      alt={alt}
      size={104}
      priority
      className={className}
    />
  );
}

/** Says, to a screen reader, whose listing the page now shows. Silent on load. */
export function ShopViewStatus() {
  const view = useShopView();
  const current = view && view.picks > 0 ? view.meta[view.picked] : null;
  return (
    <p role="status" className="sr-only" data-shop-view-status>
      {current ? `Showing ${current.shop}’s listing` : ""}
    </p>
  );
}

/**
 * Under the title, with makhzan's other facts, when any offer was matched by
 * AI: how many, and a way to say one is not the same product, which opens
 * Report a problem on that reason with the AI-matched offers listed first.
 */
export function AiNote({ count, total }: { count: number; total: number }) {
  // The report form needs JavaScript; until it runs, "tell us" is plain text.
  const ready = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  if (count === 0) return null;
  return (
    <p data-ai-note className="mt-1.5 text-[13px] leading-snug text-ink-2 lg:text-sm">
      {aiNoteText(count, total)} If one isn’t the same product,{" "}
      {ready ? (
        <button
          type="button"
          data-ai-report
          onClick={() => openOffersReport()}
          className="relative cursor-pointer font-medium text-link underline outline-offset-2 outline-link after:absolute after:-inset-x-1 after:-inset-y-3.5 after:content-[''] focus-visible:outline-2"
        >
          tell us
        </button>
      ) : (
        "tell us"
      )}
      .
    </p>
  );
}
