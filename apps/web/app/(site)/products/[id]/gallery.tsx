import { PhotoFrame } from "@/components/photo-frame";
import { cn } from "@/lib/utils";

/**
 * The product's photos as a swipeable strip: CSS scroll snapping, no
 * JavaScript. Each photo carries its own "2 / 3", so the count is right
 * whichever one is on screen without anything having to track it.
 *
 * Photos come from every shop's listing (21% of listings have several), all
 * contained in the white frame (rule S5).
 */
export function Gallery({
  images,
  alt,
  frameClassName,
  priority = false,
}: {
  images: string[];
  alt: string;
  /** Shape of each frame, e.g. 4:3 on a phone. */
  frameClassName?: string;
  priority?: boolean;
}) {
  if (images.length <= 1) {
    return (
      <PhotoFrame
        src={images[0] ?? null}
        alt={alt}
        priority={priority}
        className={frameClassName}
      />
    );
  }
  return (
    <div
      role="group"
      aria-label={`${images.length} photos`}
      data-gallery
      className="flex snap-x snap-mandatory gap-2 overflow-x-auto overscroll-x-contain"
    >
      {images.map((src, index) => (
        <div key={src} className="relative w-full shrink-0 snap-center">
          <PhotoFrame
            src={src}
            alt={index === 0 ? alt : `${alt}, photo ${index + 1}`}
            priority={priority && index === 0}
            className={frameClassName}
          />
          <span
            aria-hidden="true"
            className={cn(
              "absolute end-2.5 bottom-2.5 rounded-full border border-line bg-surface px-2 text-xs",
              "text-ink-2 tabular",
            )}
          >
            {index + 1} / {images.length}
          </span>
        </div>
      ))}
    </div>
  );
}
