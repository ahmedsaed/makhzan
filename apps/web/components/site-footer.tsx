import { Link } from "@/components/link";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { routes } from "@/lib/routes";

/**
 * The footer's links, in three labelled groups (the owner's choice over one
 * long row, November 2026): makhzan itself; the pages a supplier needs, on
 * every page because a shop owner can arrive anywhere; and the legal pages.
 */
export const FOOTER_GROUPS = [
  {
    title: "makhzan",
    links: [
      { label: "About", href: routes.about() },
      { label: "FAQ", href: routes.faq() },
      { label: "Contact", href: routes.contact() },
    ],
  },
  {
    title: "For shops",
    links: [
      { label: "For suppliers", href: routes.forSuppliers() },
      { label: "How we crawl", href: routes.howWeCrawl() },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Privacy", href: routes.privacy() },
      { label: "Terms", href: routes.terms() },
    ],
  },
] as const;

/**
 * On a phone: the logo, two columns of groups, then the theme toggle and
 * "Made by Merope". From `md`, the groups sit in a row beside the logo and
 * the toggle moves to the right. Every link is 44 px tall (S4).
 *
 * One "Footer" landmark holds the three groups, each a list named by its
 * visible heading: three navs made a screen reader's landmark list three
 * entries longer for one footer.
 *
 * No data fetching, for the same reason as the header: it renders on error
 * pages and must not depend on the API.
 */
export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-start gap-x-6 gap-y-3 px-4 py-6 text-sm md:px-6">
        <Link
          href={routes.home()}
          aria-label="makhzan, home"
          className="mt-1 flex h-11 shrink-0 items-center"
        >
          <Logo className="text-lg" />
        </Link>
        <nav
          aria-label="Footer"
          className="grid flex-[1_1_100%] grid-cols-2 gap-x-6 gap-y-1 md:flex-[0_1_auto] md:grid-cols-[repeat(3,auto)] md:gap-x-14"
        >
          {FOOTER_GROUPS.map((group) => {
            const headingId = `footer-group-${group.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
            return (
              <div key={group.title} data-footer-group={group.title}>
                <h2
                  id={headingId}
                  className="mt-2.5 font-sans text-xs font-semibold tracking-[0.06em] text-ink-3 uppercase"
                >
                  {group.title}
                </h2>
                <ul aria-labelledby={headingId} className="flex flex-col items-start">
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className="flex h-11 items-center text-ink-2 hover:text-ink"
                      >
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <div className="flex flex-[1_1_100%] flex-wrap items-center gap-x-6 gap-y-3 md:flex-[1_1_auto] md:justify-end md:self-center">
          <ThemeToggle />
          <p className="text-ink-2">
            Made by{" "}
            <a href="https://merope.dev" className="text-link underline">
              Merope
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
