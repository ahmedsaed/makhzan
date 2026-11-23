import { fetchCrawlerAddresses } from "@/lib/api";

/**
 * /crawler-addresses.json: the addresses our crawler sends from, for firewalls
 * and scripts, in the shape Google publishes for Googlebot (`prefixes`, each
 * an `ipv6Prefix` or `ipv4Prefix`), so allow-list tools that read that file
 * can read this one. The list itself is the worker's, stated only once the
 * owner publishes it (GET /crawler/addresses); until then, 404.
 *
 * `shared` marks the server's own IPv4, which also carries other services and
 * so has no crawler reverse DNS.
 */
export async function GET() {
  const addresses = await fetchCrawlerAddresses();
  if (!addresses) {
    return new Response(JSON.stringify({ error: "no crawler addresses are published" }), {
      status: 404,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
  const body = {
    creationTime: addresses.updated_at,
    reverseDns: addresses.reverse_dns,
    prefixes: [
      ...addresses.ipv6.map((address) => ({ ipv6Prefix: `${address}/128` })),
      ...addresses.ipv4.map((entry) => ({
        ipv4Prefix: `${entry.address}/32`,
        ...(entry.shared ? { shared: true } : {}),
      })),
    ],
  };
  return new Response(`${JSON.stringify(body, null, 2)}\n`, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=600",
    },
  });
}

/** Read from the API when requested, not baked in at build. */
export const dynamic = "force-dynamic";
