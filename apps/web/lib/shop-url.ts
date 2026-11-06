/**
 * The one way out of makhzan (rule P4).
 *
 * Every link to a shop carries `ref=makhzan`, so a shop can see in its own
 * analytics how many visitors we sent — the number the conversation with
 * suppliers rests on (docs/PRODUCT.md). The shop's own parameters are kept: some
 * product URLs only resolve with them.
 */

export const REF_PARAM = "ref";
export const REF_VALUE = "makhzan";

export function shopUrl(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.searchParams.set(REF_PARAM, REF_VALUE);
    return parsed.toString();
  } catch {
    // Not an absolute URL. Supplier data is not guaranteed to be clean, and a
    // link without the tag beats no link at all.
    return url;
  }
}
