import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { markSvg, palette } from "@/lib/brand";
import { siteUrl } from "@/lib/site";

/**
 * Link-preview cards: what a shared makhzan link shows in a chat or a feed.
 *
 * One layout in the brand's style (docs/DESIGN.md, "Brand"): the light ground,
 * the logo top left, an Archivo headline, a few lines of facts, the site's
 * domain, and a burnt-orange bar along the bottom. A product card adds its
 * photo on the right, in a white frame like everywhere else (rule S5).
 *
 * Drawn by `next/og`, which reads inline styles only, so colours come from
 * lib/brand.ts rather than the CSS tokens.
 */

export const OG_SIZE = { width: 1200, height: 630 };

/** The fonts are committed (assets/fonts, OFL) and read from disk once. A card
 *  must never depend on a font host being up. */
let fonts: Promise<{ name: string; data: Buffer; weight: 500 | 700 | 800 }[]> | null = null;

function loadFonts() {
  const dir = join(process.cwd(), "assets/fonts");
  fonts ??= Promise.all([
    readFile(join(dir, "Archivo-ExtraBold.ttf")).then((data) => ({
      name: "Archivo",
      data,
      weight: 800 as const,
    })),
    readFile(join(dir, "Archivo-Bold.ttf")).then((data) => ({
      name: "Archivo",
      data,
      weight: 700 as const,
    })),
    readFile(join(dir, "Inter-Medium.ttf")).then((data) => ({
      name: "Inter",
      data,
      weight: 500 as const,
    })),
  ]).catch((error) => {
    // Not cached: a missing file is a deploy fault worth seeing on the next
    // request too. The card still renders, in the renderer's own face.
    fonts = null;
    console.error("og: fonts not loaded", error);
    return [];
  });
  return fonts;
}

/** Cut at a word boundary with an ellipsis, so a long title never runs off
 *  the card. Satori wraps but does not clamp. */
export function clampText(text: string, max: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,.;:–-]+$/, "")}…`;
}

// --------------------------------------------------------------------------- //
// The product photo
// --------------------------------------------------------------------------- //

/** How long a shop gets to send its photo before the card goes without it. */
const PHOTO_TIMEOUT_MS = 3000;
/** A week: the photo is the same file until the shop replaces it, and every
 *  fetch is a request from our address to the shop (docs/decisions/0003). */
const PHOTO_TTL = 7 * 24 * 3600;
const PHOTO_MAX_BYTES = 4 * 1024 * 1024;
const PHOTO_BOX = 400;

/**
 * One product photo as a PNG data URL the renderer can draw, or null.
 *
 * The renderer reads PNG and JPEG only (a WebP fails the whole image, and
 * fails it late, while the response streams). So every photo goes through
 * sharp, which also shrinks it to the frame; without sharp only PNG and JPEG
 * pass, as they are. Any failure, timeout or odd format means no photo, never
 * no card.
 */
export type Photo = { src: string; width: number; height: number };

export async function fetchPhoto(src: string | null): Promise<Photo | null> {
  if (!src || !/^https?:\/\//i.test(src)) return null;
  try {
    const res = await fetch(src, {
      signal: AbortSignal.timeout(PHOTO_TIMEOUT_MS),
      headers: { accept: "image/png,image/jpeg,image/webp,image/*;q=0.8" },
      next: { revalidate: PHOTO_TTL },
    });
    if (!res.ok) return null;
    const type = (res.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
    if (type && !type.startsWith("image/")) return null;
    const body = Buffer.from(await res.arrayBuffer());
    if (body.length === 0 || body.length > PHOTO_MAX_BYTES) return null;
    return await asPng(body, type);
  } catch {
    return null;
  }
}

async function asPng(body: Buffer, type: string): Promise<Photo | null> {
  try {
    const { default: sharp } = await import("sharp");
    const { data, info } = await sharp(body)
      .resize(PHOTO_BOX, PHOTO_BOX, { fit: "inside", withoutEnlargement: true })
      .flatten({ background: palette.photoFrame })
      .png()
      .toBuffer({ resolveWithObject: true });
    // Small thumbnails are scaled up to the frame by the renderer, in proportion.
    const scale = PHOTO_BOX / Math.max(info.width, info.height);
    return {
      src: `data:image/png;base64,${data.toString("base64")}`,
      width: Math.round(info.width * scale),
      height: Math.round(info.height * scale),
    };
  } catch {
    // No sharp, or a file it cannot read: only what the renderer reads itself,
    // drawn into a square, contained.
    if (type === "image/png" || type === "image/jpeg") {
      return {
        src: `data:${type};base64,${body.toString("base64")}`,
        width: PHOTO_BOX,
        height: PHOTO_BOX,
      };
    }
    return null;
  }
}

// --------------------------------------------------------------------------- //
// The card
// --------------------------------------------------------------------------- //

export type CardProps = {
  /** The headline: the tagline, a product's title, a department or shop name. */
  title: string;
  /** Lines under the headline. The first is set large, as the key fact. */
  lead?: string | null;
  lines?: (string | null | undefined)[];
  /** A product photo, from `fetchPhoto`. */
  photo?: Photo | null;
};

const MARK_URL = `data:image/svg+xml;utf8,${encodeURIComponent(markSvg())}`;

function Card({ title, lead, lines = [], photo }: CardProps) {
  // A card prerendered by `next build` has no SITE_URL to read, and the dev
  // fallback is not an address to print; it shows once the card revalidates.
  const host = process.env.SITE_URL ? siteUrl().host : null;
  const long = title.length > 60;
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: palette.ground,
        color: palette.ink,
        fontFamily: "Inter",
      }}
    >
      <div style={{ display: "flex", flex: 1, padding: "56px 64px 40px", gap: 48 }}>
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- drawn by next/og, not the browser */}
            <img src={MARK_URL} width={58} height={58} alt="" />
            <span
              style={{
                fontFamily: "Archivo",
                fontWeight: 800,
                fontSize: 44,
                letterSpacing: "-0.02em",
              }}
            >
              makhzan
            </span>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              flex: 1,
              justifyContent: "center",
              gap: 20,
            }}
          >
            <div
              style={{
                fontFamily: "Archivo",
                fontWeight: 800,
                fontSize: photo ? (long ? 46 : 54) : long ? 54 : 64,
                lineHeight: 1.1,
                letterSpacing: "-0.01em",
              }}
            >
              {title}
            </div>
            {lead && (
              <div style={{ fontFamily: "Archivo", fontWeight: 700, fontSize: 40 }}>{lead}</div>
            )}
            {lines.filter(Boolean).map((line) => (
              <div key={line} style={{ fontSize: 28, fontWeight: 500, color: palette.ink2 }}>
                {line}
              </div>
            ))}
          </div>

          <div style={{ display: "flex", fontSize: 24, fontWeight: 500, color: palette.ink2 }}>
            {host ?? ""}
          </div>
        </div>

        {photo && (
          <div
            style={{
              display: "flex",
              alignSelf: "center",
              alignItems: "center",
              justifyContent: "center",
              width: PHOTO_BOX + 32,
              height: PHOTO_BOX + 32,
              background: palette.photoFrame,
              border: `2px solid ${palette.line}`,
              borderRadius: 16,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- drawn by next/og, not the browser */}
            <img
              src={photo.src}
              width={photo.width}
              height={photo.height}
              alt=""
              style={{ objectFit: "contain" }}
            />
          </div>
        )}
      </div>
      <div style={{ display: "flex", height: 6, background: palette.brand }} />
    </div>
  );
}

/**
 * The card as a PNG response. Rendered to a buffer here, not streamed: a
 * photo the renderer chokes on would otherwise fail mid-stream, after the 200
 * has gone out. A failed render is retried without the photo.
 */
export async function renderCard(props: CardProps): Promise<Response> {
  const fontData = await loadFonts();
  const render = async (card: CardProps) =>
    new ImageResponse(<Card {...card} />, { ...OG_SIZE, fonts: fontData }).arrayBuffer();

  let png: ArrayBuffer;
  try {
    png = await render(props);
  } catch (error) {
    if (!props.photo) throw error;
    png = await render({ ...props, photo: null });
  }
  return new Response(png, { headers: { "content-type": "image/png" } });
}
