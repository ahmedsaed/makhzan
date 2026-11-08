"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { ArrowButton, jumpStrip, stepStrip, TAP_EXTENSION, useStrip } from "./carousel";
import { FullSizePhoto } from "./full-size-photo";

/**
 * Opens the gallery's photos full-screen. Wraps the gallery: each photo in it
 * is a link (`a[data-photo="<index>"]`) to the image itself, so without
 * JavaScript a tap still opens the photo. With it, the click is caught here
 * and the photo opens in a native modal `<dialog>` instead: the rest of the
 * page goes inert, so focus stays inside, and Esc closes it.
 *
 * Inside, the photos are another scroll-snap strip, so a phone swipes between
 * them; arrows and the Left and Right keys move one photo, and "n / N" says
 * where you are. Each photo keeps its white frame (rule S5), as big as the
 * screen allows, and is swapped for its full-size original (FullSizePhoto)
 * once it is on screen. Nothing in the viewer exists until it opens, so a
 * visitor who never opens it downloads nothing for it.
 *
 * Closing returns focus to the gallery's link for the photo last shown, which
 * scrolls the gallery to it.
 */
export function PhotoViewer({
  images,
  alt,
  children,
}: {
  images: string[];
  alt: string;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [start, setStart] = useState<number | null>(null);
  const shown = useRef(0);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const onClick = (event: MouseEvent) => {
      // A modified click keeps its usual meaning: open the image in a tab.
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element).closest<HTMLAnchorElement>("a[data-photo]");
      if (!link || !node.contains(link) || !dialog.current) return;
      event.preventDefault();
      const index = Number(link.dataset.photo) || 0;
      shown.current = index;
      // Open first, so the strip inside has a size when it is laid out.
      dialog.current.showModal();
      setStart(index);
    };
    node.addEventListener("click", onClick);
    return () => node.removeEventListener("click", onClick);
  }, []);

  const onClose = () => {
    setStart(null);
    box.current
      ?.querySelector<HTMLAnchorElement>(`a[data-photo="${shown.current}"]`)
      ?.focus({ preventScroll: false });
  };

  return (
    <div ref={box}>
      {children}
      <dialog
        ref={dialog}
        aria-label={`Photos: ${alt}`}
        data-viewer
        onClose={onClose}
        className="m-0 h-dvh max-h-none w-screen max-w-none bg-scrim p-0 text-ink backdrop:bg-scrim"
      >
        {start !== null && (
          <Slides
            images={images}
            alt={alt}
            start={start}
            onIndex={(index) => {
              shown.current = index;
            }}
            close={() => dialog.current?.close()}
          />
        )}
      </dialog>
    </div>
  );
}

function Slides({
  images,
  alt,
  start,
  onIndex,
  close,
}: {
  images: string[];
  alt: string;
  start: number;
  onIndex: (index: number) => void;
  close: () => void;
}) {
  const [track, setTrack] = useState<HTMLDivElement | null>(null);
  const strip = useStrip(track);
  const { index } = strip;
  const several = images.length > 1;

  // Before paint, so the viewer opens on the photo that was tapped rather
  // than flashing the first one.
  useLayoutEffect(() => {
    if (track) jumpStrip(track, start);
  }, [track, start]);

  useEffect(() => {
    onIndex(index);
  }, [index, onIndex]);

  useEffect(() => {
    if (!several) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") stepStrip(track, -1);
      else if (event.key === "ArrowRight") stepStrip(track, 1);
      else return;
      event.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [track, several]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 p-3">
        <span
          data-viewer-count
          aria-live="polite"
          className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-sm text-ink-2 tabular"
        >
          {Math.min(index, images.length - 1) + 1} / {images.length}
        </span>
        <button
          type="button"
          aria-label="Close"
          // The dialog opened empty; focus goes to its first control once
          // there is one, which keeps Tab inside it from the start.
          autoFocus
          onClick={close}
          className={cn(
            "relative inline-flex size-11 cursor-pointer items-center justify-center rounded-full border border-line-strong bg-surface text-ink outline-offset-2 outline-link hover:border-ink-3 focus-visible:outline-2",
            TAP_EXTENSION,
          )}
        >
          <X aria-hidden="true" className="size-5" />
        </button>
      </div>
      <div className="relative min-h-0 flex-1">
        <div
          ref={setTrack}
          className="flex h-full snap-x snap-mandatory overflow-x-auto overscroll-x-contain"
        >
          {images.map((src, i) => (
            <div
              key={src}
              data-viewer-slide={i}
              className="flex w-full shrink-0 snap-center items-center justify-center px-4 pb-4"
            >
              <FullSizePhoto
                src={src}
                alt={i === 0 ? alt : `${alt}, photo ${i + 1}`}
                priority={i === start}
                // As big as the screen allows, square like every frame.
                className="w-[min(calc(100vw-2rem),calc(100dvh-6rem))] max-w-none"
              />
            </div>
          ))}
        </div>
        {several && (
          <>
            <ArrowButton
              direction={-1}
              label="Previous photo"
              disabled={strip.atStart}
              onClick={() => stepStrip(track, -1)}
            />
            <ArrowButton
              direction={1}
              label="Next photo"
              disabled={strip.atEnd}
              onClick={() => stepStrip(track, 1)}
            />
          </>
        )}
      </div>
    </div>
  );
}
