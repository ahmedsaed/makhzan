import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Tajawal } from "next/font/google";
import { notFound } from "next/navigation";

import "../globals.css";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ThemeProvider } from "@/components/theme-provider";
import { LANGS, dirOf, getDictionary, isLang, type Lang } from "@/lib/i18n";

/**
 * The root layout, and it lives under `[lang]` on purpose: `lang` and `dir` are
 * attributes of the server-rendered document, not something an effect corrects
 * after hydration. That is what makes an Arabic page linkable and indexable.
 */

// Display face — titles and the wordmark. Latin only; Arabic titles use Tajawal.
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-archivo",
  display: "swap",
});

// Body face, and the reason the pairing works: Tajawal covers Latin and Arabic
// with matching weights, so a bilingual title does not change texture mid-line.
const tajawal = Tajawal({
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "700"],
  variable: "--font-tajawal",
  display: "swap",
});

// Part numbers, prices, counts — anything that gets compared down a column.
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

// Cookieless page-view counts from our own Umami (stats.merope.dev). Inlined at
// build; only the production image sets it, so dev and CI builds count nothing.
const umamiWebsiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;

export function generateStaticParams() {
  return LANGS.map((lang) => ({ lang }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string }>;
}): Promise<Metadata> {
  const { lang } = await params;
  if (!isLang(lang)) return {};
  const t = getDictionary(lang);
  return {
    title: { default: `${t.brand} — ${t.tagline}`, template: `%s · ${t.brand}` },
    description: t.heroLead,
    // Both languages are equal citizens; neither is a translation of the other.
    alternates: {
      canonical: `/${lang}`,
      languages: { en: "/en", ar: "/ar" },
    },
  };
}

export default async function LangLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ lang: string }>;
}) {
  const { lang } = await params;
  if (!isLang(lang)) notFound();
  const typed: Lang = lang;

  return (
    <html
      lang={typed}
      dir={dirOf(typed)}
      suppressHydrationWarning
      className={`${archivo.variable} ${tajawal.variable} ${plexMono.variable}`}
    >
      <body className="flex min-h-svh flex-col">
        <ThemeProvider>
          <SiteHeader lang={typed} />
          <main className="flex-1">{children}</main>
          <SiteFooter lang={typed} />
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
