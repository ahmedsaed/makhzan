/**
 * Two production products and their price history, as the API served them
 * on 2026-11-13 (real-history.json, shops anonymised), for the history bug
 * that real data showed and the made-up fixtures did not (a stale offer's lone
 * seeded point setting when recording began).
 *
 * Every timestamp is moved forward by the time since the snapshot, so the
 * page sees the data exactly as it was that day whenever the suite runs.
 */
import { readFileSync } from "node:fs";

const REAL = JSON.parse(readFileSync(new URL("./real-history.json", import.meta.url), "utf8"));
const SHIFT = Date.now() - Date.parse(REAL.captured_at);
const ISO = /^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:\d{2})?$/;

/** A deep copy with every ISO timestamp moved by SHIFT. */
function shifted(value) {
  if (Array.isArray(value)) return value.map(shifted);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shifted(v)]));
  }
  if (typeof value === "string" && ISO.test(value)) {
    return new Date(Date.parse(value) + SHIFT).toISOString();
  }
  return value;
}

const PRODUCTS = shifted(REAL.products);
const HISTORIES = shifted(REAL.histories);

/** `[status, body]` for a path this fixture owns, or null. */
export function realHistoryFixture(path) {
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
