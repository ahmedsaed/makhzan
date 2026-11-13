/**
 * Two production products and their price history, as the API served them
 * on 2026-11-13 (real-history.json, shops anonymised), for the history bug
 * that real data showed and the made-up fixtures did not (a stale offer's lone
 * seeded point setting when recording began).
 *
 * Every timestamp is moved forward by the time since the snapshot, on each
 * request, so the page sees the data exactly as it was that day whenever the
 * suite runs.
 */
import { readFileSync } from "node:fs";

const REAL = JSON.parse(readFileSync(new URL("./real-history.json", import.meta.url), "utf8"));
const ISO = /^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:\d{2})?$/;

/** A deep copy with every ISO timestamp moved by `shift` milliseconds. */
function shifted(value, shift) {
  if (Array.isArray(value)) return value.map((v) => shifted(v, shift));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shifted(v, shift)]));
  }
  if (typeof value === "string" && ISO.test(value)) {
    return new Date(Date.parse(value) + shift).toISOString();
  }
  return value;
}

/** `[status, body]` for a path this fixture owns, or null. */
export function realHistoryFixture(path) {
  // Shifted per request, against the clock the page renders with, so a stub
  // left running for hours (reuseExistingServer) does not drift from it. In
  // whole hours: the product and its history are fetched (and cached by Next
  // for minutes) separately, and must carry the same shift, or a stale
  // offer's baseline lands before its own last check. An hour is well inside
  // the margins the tests rely on (TB6600 is 9 h past its 30 days).
  const HOUR = 3_600_000;
  const shift = Math.floor((Date.now() - Date.parse(REAL.captured_at)) / HOUR) * HOUR;
  const PRODUCTS = shifted(REAL.products, shift);
  const HISTORIES = shifted(REAL.histories, shift);
  const history = path.match(/^\/products\/([^/]+)\/history$/)?.[1];
  if (history && HISTORIES[history]) return [200, HISTORIES[history]];
  const similar = path.match(/^\/products\/([^/]+)\/similar$/)?.[1];
  if (similar && PRODUCTS[similar]) return [200, []];
  const id = path.match(/^\/products\/([^/]+)$/)?.[1];
  if (id && PRODUCTS[id]) return [200, PRODUCTS[id]];
  const listing = path.match(/^\/listings\/([^/]+)$/)?.[1];
  for (const product of Object.values(PRODUCTS)) {
    const offer = product.offers.find((o) => o.id === listing);
    if (offer) {
      return [
        200,
        {
          ...offer,
          product_id: product.id,
          description_en: null,
          description_ar: null,
          part_number: product.part_number,
          unit: null,
          status: "active",
          category: null,
        },
      ];
    }
  }
  return null;
}
