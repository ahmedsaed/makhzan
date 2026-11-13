import { describe, expect, it } from "vitest";

import {
  ANSWER_AGENTS,
  CONTENT_SIGNAL,
  FILTER_PARAMS,
  PACED_CRAWLERS,
  REFUSED_CRAWLERS,
  robotsTxt,
} from "@/lib/robots";

const SITEMAP = "https://makhzan.example/sitemap.xml";
const TEXT = robotsTxt(SITEMAP);

type Group = { agents: string[]; lines: [string, string][] };

/** The file's groups: consecutive User-agent lines open one, rules follow. */
function groups(text: string): Group[] {
  const out: Group[] = [];
  let current: Group | null = null;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/#.*/, "").trim();
    if (!line) continue;
    const [key, ...rest] = line.split(":");
    const field = key.trim().toLowerCase();
    const value = rest.join(":").trim();
    if (field === "user-agent") {
      if (!current || current.lines.length > 0) out.push((current = { agents: [], lines: [] }));
      current.agents.push(value.toLowerCase());
    } else if (current && field !== "sitemap") {
      current.lines.push([field, value]);
    }
  }
  return out;
}

/** The group a crawler obeys (RFC 9309: its own name, else `*`). */
function groupFor(agent: string): Group {
  const all = groups(TEXT);
  return (
    all.find((group) => group.agents.includes(agent.toLowerCase())) ??
    all.find((group) => group.agents.includes("*"))!
  );
}

/** RFC 9309 matching, as Google and Bing do it: `*` wildcards, longest rule
 *  wins, Allow wins a tie. */
function allowed(agent: string, path: string): boolean {
  let best: { length: number; allow: boolean } | null = null;
  for (const [field, pattern] of groupFor(agent).lines) {
    if (field !== "allow" && field !== "disallow") continue;
    if (!pattern) continue;
    const regex = new RegExp(
      "^" + pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*"),
    );
    if (!regex.test(path)) continue;
    const allow = field === "allow";
    if (!best || pattern.length > best.length || (pattern.length === best.length && allow)) {
      best = { length: pattern.length, allow };
    }
  }
  return best?.allow ?? true;
}

/**
 * First-match semantics, as CPython's urllib.robotparser applies them: the
 * group's rules in file order, the first whose path matches decides.
 * `wildcards` false reads `*` literally (robotparser does, as of 3.12);
 * true expands it, as some other first-match parsers do.
 */
function allowedFirstMatch(agent: string, path: string, wildcards: boolean): boolean {
  for (const [field, pattern] of groupFor(agent).lines) {
    if (field !== "allow" && field !== "disallow") continue;
    if (!pattern) continue;
    const matches = wildcards
      ? new RegExp(
          "^" + pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*"),
        ).test(path)
      : path.startsWith(pattern);
    if (matches) return field === "allow";
  }
  return true;
}

/** Pages crawlers should reach: the sitemap's own and plain paging. */
const CANONICAL = [
  "/",
  "/departments",
  "/departments/electronics",
  "/departments/electronics/sensors",
  "/departments/electronics/sensors?offset=48",
  "/shops",
  "/shops/some-shop",
  "/shops/some-shop?offset=24",
  "/products/1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-sg90-micro-servo-180",
  "/how-we-crawl",
];

/** Filter combinations, wherever the parameter sits in the query. */
const FILTERED = [
  "/departments/electronics?stale=all",
  "/departments/electronics/sensors?in_stock=all&stale=all",
  "/departments/electronics/sensors?offset=24&sort=price:asc",
  "/departments?domain=tools",
  "/departments/tools?category=tools:measurement",
  "/shops/some-shop?q=servo",
  "/shops/some-shop?offset=24&min_price=10&max_price=90",
  "/shops/some-shop?min_suppliers=2",
  "/shops?shop=x",
];

describe("robots.txt", () => {
  it("signals search and AI input yes, training no, to everyone", () => {
    expect(TEXT).toContain(`User-agent: *\nContent-Signal: ${CONTENT_SIGNAL}\nDisallow: /search\n`);
    expect(CONTENT_SIGNAL).toBe("search=yes, ai-input=yes, ai-train=no");
  });

  it("refuses under first-match parsers too: no Allow line can win first", () => {
    expect(TEXT).not.toMatch(/^Allow:/m);
    for (const agent of ["Googlebot", ...PACED_CRAWLERS]) {
      for (const wildcards of [false, true]) {
        expect(allowedFirstMatch(agent, "/search?q=servo", wildcards)).toBe(false);
        expect(allowedFirstMatch(agent, "/api/search", wildcards)).toBe(false);
        for (const path of CANONICAL) {
          expect(allowedFirstMatch(agent, path, wildcards), path).toBe(true);
        }
      }
      // A literal-`*` parser cannot read the facet rules at all; one that
      // expands `*` refuses them in first-match order as well.
      for (const path of FILTERED) expect(allowedFirstMatch(agent, path, true), path).toBe(false);
    }
  });

  it("names the sitemap index", () => {
    expect(TEXT).toContain(`Sitemap: ${SITEMAP}\n`);
  });

  it.each(REFUSED_CRAWLERS)("refuses %s everything", (agent) => {
    expect(groupFor(agent).agents).toContain(agent.toLowerCase());
    expect(allowed(agent, "/")).toBe(false);
    expect(allowed(agent, "/departments/electronics")).toBe(false);
  });

  it("refuses every training and backlink crawler the policy names", () => {
    for (const agent of [
      "GPTBot", "ClaudeBot", "Amazonbot", "Reflectionbot", "ElevenlabsCrawler", "CCBot",
      "Google-Extended", "Applebot-Extended", "meta-externalagent", "Bytespider",
      "SemrushBot", "SERankingBacklinksBot", "DotBot", "AhrefsBot",
    ]) {
      expect(REFUSED_CRAWLERS).toContain(agent);
    }
  });

  it.each(ANSWER_AGENTS)("leaves %s under the general rules", (agent) => {
    expect(TEXT).not.toMatch(new RegExp(`^User-agent: ${agent}$`, "mi"));
    expect(groupFor(agent).agents).toEqual(["*"]);
    for (const path of CANONICAL) expect(allowed(agent, path), path).toBe(true);
  });

  it.each(["Googlebot", ...PACED_CRAWLERS])("keeps %s off search and the filters", (agent) => {
    for (const path of CANONICAL) expect(allowed(agent, path), path).toBe(true);
    for (const path of FILTERED) expect(allowed(agent, path), path).toBe(false);
    expect(allowed(agent, "/search?q=servo")).toBe(false);
    expect(allowed(agent, "/api/search")).toBe(false);
  });

  it("refuses each filter in either position", () => {
    for (const param of FILTER_PARAMS) {
      expect(allowed("Googlebot", `/departments/x?${param}=1`), param).toBe(false);
      expect(allowed("Googlebot", `/shops/x?offset=24&${param}=1`), param).toBe(false);
    }
  });

  it("paces Claude-SearchBot and Bingbot, with the general rules repeated", () => {
    for (const agent of PACED_CRAWLERS) {
      const group = groupFor(agent);
      expect(group.agents).toEqual(PACED_CRAWLERS.map((a) => a.toLowerCase()));
      expect(group.lines).toContainEqual(["crawl-delay", "5"]);
      expect(group.lines).toContainEqual(["content-signal", CONTENT_SIGNAL]);
      const rules = (g: Group) => g.lines.filter(([field]) => field.endsWith("allow"));
      expect(rules(group)).toEqual(rules(groupFor("*")));
    }
  });
});
