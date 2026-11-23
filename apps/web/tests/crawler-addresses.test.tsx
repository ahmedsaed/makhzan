/**
 * The crawler's published addresses: the Addresses tab on /how-we-crawl and
 * /crawler-addresses.json. Both show nothing until the worker states a list
 * (GET /crawler/addresses answers 404 until the owner publishes it).
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrawlerAddresses } from "@/lib/api";
import { crawlingContent } from "@/lib/content/crawling";

const api = vi.hoisted(() => ({
  fetchCrawlerActivity: vi.fn(async () => null),
  fetchCrawlerAddresses: vi.fn<() => Promise<CrawlerAddresses | null>>(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  ...api,
}));

const { default: HowWeCrawlPage } = await import("@/app/(site)/how-we-crawl/page");
const { GET } = await import("@/app/crawler-addresses.json/route");

const PUBLISHED: CrawlerAddresses = {
  reverse_dns: "crawler.example.dev",
  ipv6: ["2001:4860:4860::8888", "2001:4860:4860::8844"],
  ipv4: [{ address: "8.8.8.8", shared: true }],
  updated_at: "2026-11-23T12:00:00+00:00",
};

const { verify } = crawlingContent;

beforeEach(() => {
  api.fetchCrawlerAddresses.mockReset();
});

describe("the Addresses tab", () => {
  it("is absent, and the page says no addresses are published, until a list is", async () => {
    api.fetchCrawlerAddresses.mockResolvedValue(null);
    render(await HowWeCrawlPage());
    expect(screen.queryByText(verify.tabs.addresses.label)).toBeNull();
    expect(screen.getByText(verify.noAddresses)).toBeInTheDocument();
  });

  it("lists every address, the reverse DNS check and the shared IPv4", async () => {
    api.fetchCrawlerAddresses.mockResolvedValue(PUBLISHED);
    const { container } = render(await HowWeCrawlPage());
    const panel = container.querySelector("[data-crawler-addresses]");
    expect(panel).not.toBeNull();
    for (const address of PUBLISHED.ipv6) expect(panel).toHaveTextContent(address);
    expect(panel).toHaveTextContent("It should be crawler.example.dev.");
    expect(panel).toHaveTextContent("our server's address, 8.8.8.8");
    expect(panel).toHaveTextContent("/crawler-addresses.json");
    expect(screen.queryByText(verify.noAddresses)).toBeNull();
    expect(screen.getByText(verify.withAddresses.title)).toBeInTheDocument();
  });

  it("calls a dedicated IPv4 address a crawler address, not the server's", async () => {
    api.fetchCrawlerAddresses.mockResolvedValue({
      ...PUBLISHED,
      ipv4: [{ address: "8.8.4.4", shared: false }],
    });
    const { container } = render(await HowWeCrawlPage());
    const panel = container.querySelector("[data-crawler-addresses]");
    expect(panel).toHaveTextContent("read from 8.8.4.4, which is used for crawling only");
    expect(panel).not.toHaveTextContent("our server's address");
  });
});

describe("/crawler-addresses.json", () => {
  it("is 404 until a list is published", async () => {
    api.fetchCrawlerAddresses.mockResolvedValue(null);
    expect((await GET()).status).toBe(404);
  });

  it("uses the prefixes shape Google publishes for Googlebot", async () => {
    api.fetchCrawlerAddresses.mockResolvedValue(PUBLISHED);
    const response = await GET();
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(await response.json()).toEqual({
      creationTime: PUBLISHED.updated_at,
      reverseDns: "crawler.example.dev",
      prefixes: [
        { ipv6Prefix: "2001:4860:4860::8888/128" },
        { ipv6Prefix: "2001:4860:4860::8844/128" },
        { ipv4Prefix: "8.8.8.8/32", shared: true },
      ],
    });
  });
});
