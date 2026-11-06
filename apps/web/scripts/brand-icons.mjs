/**
 * Draws the raster icons from the mark, so they are never edited by hand:
 *
 *   app/icon.png              32px tab icon, for browsers without SVG favicons
 *   app/favicon.ico           16, 32 and 48px, for whatever still asks for one
 *   app/apple-icon.png        180px home-screen tile (iOS rounds the corners)
 *   public/icon-192.png       web app manifest
 *   public/icon-512.png       web app manifest, and the Organization logo
 *   public/icon-maskable-512.png  manifest, cropped to a circle or squircle
 *
 * The small icons are a rounded tile on the light ground, so the dark outline
 * reads on a dark tab bar too; the large ones are a full square, because the
 * platform rounds or masks them itself. Colours and geometry are the ones in
 * lib/brand.ts and docs/DESIGN.md ("Brand").
 *
 * Run from apps/web after changing the mark: `node scripts/brand-icons.mjs`.
 */
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

import sharp from "sharp";

const ROOT = join(import.meta.dirname, "..");
const GROUND = "#F6F6F3";
const INK = "#15171C";
const BRAND = "#C2410C";

/** The mark's rectangles, on its 48-unit grid. */
const MARK = `
  <rect x="4" y="4" width="18" height="18" rx="4" fill="none" stroke="${INK}" stroke-width="3.5"/>
  <rect x="26" y="4" width="18" height="18" rx="4" fill="${BRAND}"/>
  <rect x="4" y="26" width="18" height="18" rx="4" fill="none" stroke="${INK}" stroke-width="3.5"/>
  <rect x="26" y="26" width="18" height="18" rx="4" fill="none" stroke="${INK}" stroke-width="3.5"/>`;

/**
 * The mark on a ground. `scale` is the drawn mark's share of the icon's width
 * (the mark spans 2.25–45.75 of its 48 units, outline included); `radius` is
 * the tile's corner as a share of its width, 0 for a full square.
 */
function tile(size, { scale, radius }) {
  const mark = 43.5; // drawn width in mark units
  const unit = (size * scale) / mark;
  const offset = (size - 48 * unit) / 2;
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${size * radius}" fill="${GROUND}"/>
  <g transform="translate(${offset} ${offset}) scale(${unit})">${MARK}</g>
</svg>`);
}

const png = (svg) => sharp(svg).png({ compressionLevel: 9 }).toBuffer();

/** An .ico whose entries are PNGs, which every current browser reads. */
function ico(images) {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, i) => {
    const entry = 6 + 16 * i;
    header.writeUInt8(size >= 256 ? 0 : size, entry);
    header.writeUInt8(size >= 256 ? 0 : size, entry + 1);
    header.writeUInt16LE(1, entry + 4); // colour planes
    header.writeUInt16LE(32, entry + 6); // bits per pixel
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...images.map(({ data }) => data)]);
}

const small = { scale: 0.78, radius: 0.22 };
const full = { scale: 0.6, radius: 0 };
// The maskable safe zone is a centred circle 80% wide; the mark's corners
// must stay inside it.
const maskable = { scale: 0.5, radius: 0 };

const outputs = {
  "app/icon.png": await png(tile(32, small)),
  "app/apple-icon.png": await png(tile(180, full)),
  "public/icon-192.png": await png(tile(192, full)),
  "public/icon-512.png": await png(tile(512, full)),
  "public/icon-maskable-512.png": await png(tile(512, maskable)),
  "app/favicon.ico": ico(
    await Promise.all(
      [16, 32, 48].map(async (size) => ({ size, data: await png(tile(size, small)) })),
    ),
  ),
};

for (const [path, data] of Object.entries(outputs)) {
  await writeFile(join(ROOT, path), data);
  process.stdout.write(`${path} ${data.length} bytes\n`);
}
