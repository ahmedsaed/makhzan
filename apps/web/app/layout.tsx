import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Inter } from "next/font/google";

import "./globals.css";
import { SiteFooter } from "@/components/site-footer";
import { ThemeProvider } from "@/components/theme-provider";

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

export const metadata: Metadata = {
  title: {
    default: "makhzan — find parts across Egypt's shops",
    template: "%s · makhzan",
  },
  description:
    "One search across Egyptian hardware and electronics shops. Every price shows when it was last checked; buying happens on the shop's own site.",
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
