import { photoNumbered, type GalleryPhoto } from "@/lib/product";
import { shopUrl } from "@/lib/shop-url";
import { cn } from "@/lib/utils";

import { Carousel } from "./carousel";
import { FullSizePhoto } from "./full-size-photo";
import { PhotoViewer } from "./viewer";

/**
 * The product's photos as a swipeable strip: CSS scroll snapping, which works
 * without JavaScript. Each photo carries its own "2 / 3", so the count is
 * right whichever one is on screen without anything having to track it. With
 * JavaScript, previous and next buttons move one photo (Carousel).
 *
 * Photos come from every shop's listing (21% of listings have several), all
 * contained in the white frame (rule S5), and at full size where a shop only
 * hands out cached thumbnails (FullSizePhoto); the page is the one place a
 * photo is big enough for that to matter. Each is badged with its own shop
 * (PhotoFrame), so a gallery of two shops' photos says whose each one is.
 *
 * Each photo is a link to the image on the shop's site (with `ref=makhzan`,
 * rule P4), so without JavaScript a tap still opens it; with JavaScript it
 * opens the full-screen viewer instead (PhotoViewer).
 */
export function Gallery({
  photos,
  alt,
  frameClassName,
  priority = false,
}: {
  photos: GalleryPhoto[];
  alt: string;
  /** Shape of each frame, e.g. 4:3 on a phone. */
  frameClassName?: string;
  priority?: boolean;
}) {
  if (photos.length === 0) {
    return <FullSizePhoto src={null} alt={alt} priority={priority} className={frameClassName} />;
  }
  const photo = ({ src, shop }: GalleryPhoto, index: number) => (
    <a
      href={shopUrl(src)}
      target="_blank"
      rel="noopener noreferrer"
      data-photo={index}
      className="block cursor-zoom-in rounded-card outline-offset-2 outline-link focus-visible:outline-2"
    >
      <FullSizePhoto
        src={src}
        alt={photoNumbered(alt, index)}
        shop={shop}
        priority={priority && index === 0}
        className={frameClassName}
      />
    </a>
  );
  if (photos.length === 1) {
    return (
      <PhotoViewer photos={photos} alt={alt}>
        {photo(photos[0], 0)}
      </PhotoViewer>
    );
  }
  return (
    <PhotoViewer photos={photos} alt={alt}>
      <Carousel previous="Previous photo" next="Next photo">
        <div
          role="group"
          aria-label={`${photos.length} photos`}
          data-gallery
          data-carousel-track
          className="flex snap-x snap-mandatory gap-2 overflow-x-auto overscroll-x-contain"
        >
          {photos.map((item, index) => (
            <div key={item.src} data-photo-count className="relative w-full shrink-0 snap-center">
              {photo(item, index)}
              <span
                aria-hidden="true"
                className={cn(
                  "pointer-events-none absolute end-2.5 bottom-2.5 rounded-full border border-line bg-surface px-2 text-xs",
                  "text-ink-2 tabular",
                )}
              >
                {index + 1} / {photos.length}
              </span>
            </div>
          ))}
        </div>
      </Carousel>
    </PhotoViewer>
  );
}
