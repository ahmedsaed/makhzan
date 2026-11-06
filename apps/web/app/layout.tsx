import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono, Inter } from "next/font/google";

import "./globals.css";
import { SiteFooter } from "@/components/site-footer";
import { ThemeProvider } from "@/components/theme-provider";
import { darkPalette, palette, SITE_DESCRIPTION, SITE_NAME } from "@/lib/brand";
import { siteUrl } from "@/lib/site";

/**
 * The document. English only, so `lang` is fixed: Arabic titles make up 0.1% of
 * the catalogue and the bilingual interface is gone (docs/DESIGN.md). Arabic
 * queries still work; that is the search engine's business, not the layout's.
 *
 * The header is not here. The home page leads with its own large search and
 * renders a header without one; every other page gets the full header from the
 * `(site)` layout. The footer is the same everywhere.
 */

// Headings and prices.
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["700", "800"],
  variable: "--font-archivo",
  display: "swap",
});

// Everything else that is text.
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});

// Part numbers.
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["500"],
  variable: "--font-plex-mono",
  display: "swap",
});

// Cookieless page-view counts from our own Umami (stats.merope.dev). Inlined at
// build; only the production image sets it, so dev and CI builds count nothing.
// Shop clicks are counted by the same script, from the `data-umami-event`
// attributes ShopLink puts on every link out.
const umamiWebsiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;

/** A function, not a constant, so `SITE_URL` is read when a page renders
 *  rather than when the build evaluates this module. */
export function generateMetadata(): Metadata {
  return {
    // Every relative canonical resolves against this: the configured public
    // origin, never the Host header of whoever asked.
    metadataBase: siteUrl(),
    title: {
      default: `${SITE_NAME} — find parts and materials across Egypt's suppliers`,
      template: `%s · ${SITE_NAME}`,
    },
    description: SITE_DESCRIPTION,
    applicationName: SITE_NAME,
    // The defaults for a page that sets none of its own; most do, through
    // lib/metadata.ts, which repeats the site name and locale because a
    // page's `openGraph` replaces this one whole.
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "en",
      title: SITE_NAME,
      description: SITE_DESCRIPTION,
    },
    twitter: { card: "summary_large_image", title: SITE_NAME, description: SITE_DESCRIPTION },
  };
}

/** A phone's browser bar takes the page's ground, in either theme. */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: palette.ground },
    { media: "(prefers-color-scheme: dark)", color: darkPalette.ground },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      // next-themes sets the theme class before paint, which React would
      // otherwise report as a mismatch.
      suppressHydrationWarning
      className={`${archivo.variable} ${inter.variable} ${plexMono.variable}`}
    >
      <body className="flex min-h-svh flex-col">
        <ThemeProvider>
          {children}
          <SiteFooter />
        </ThemeProvider>
        {umamiWebsiteId && (
          <script
            defer
            src="https://stats.merope.dev/p.js"
            data-website-id={umamiWebsiteId}
            data-do-not-track="true"
          />
        )}
      </body>
    </html>
  );
}
