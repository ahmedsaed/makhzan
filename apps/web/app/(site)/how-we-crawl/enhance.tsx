"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

/**
 * The few things on /how-we-crawl that need JavaScript, each of which leaves
 * the page whole without it: tabs that are every panel in turn, a snippet you
 * select by hand, and a contents list of plain links.
 */

const noop = () => () => {};

/** False on the server and in the first client render, true once hydrated. */
function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}

export type TabPanel = { id: string; label: string; content: React.ReactNode };

/**
 * Tabs that degrade to every panel shown, each under its own heading. With
 * JavaScript: one tab stop, Left/Right between tabs, Home/End to the ends.
 */
export function Tabs({ label, panels }: { label: string; panels: TabPanel[] }) {
  const hydrated = useHydrated();
  const [selected, setSelected] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  function choose(index: number, focus = false) {
    const next = (index + panels.length) % panels.length;
    setSelected(next);
    if (focus) tabs.current[next]?.focus();
  }

  return (
    <div data-tabs={hydrated ? "enhanced" : "static"} className="mt-4">
      {hydrated && (
        <div
          role="tablist"
          aria-label={label}
          className="flex [scrollbar-width:none] gap-0.5 overflow-x-auto border-b border-line"
        >
          {panels.map((panel, i) => (
            <button
              key={panel.id}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${panel.id}`}
              aria-controls={`panel-${panel.id}`}
              aria-selected={i === selected}
              tabIndex={i === selected ? 0 : -1}
              onClick={() => choose(i)}
              onKeyDown={(event) => {
                const target =
                  event.key === "ArrowRight"
                    ? i + 1
                    : event.key === "ArrowLeft"
                      ? i - 1
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? panels.length - 1
                          : null;
                if (target === null) return;
                event.preventDefault();
                choose(target, true);
              }}
              className={cn(
                "-mb-px min-h-11 border-b-2 px-3 text-[14.5px] whitespace-nowrap",
                i === selected
                  ? "border-action font-semibold text-ink"
                  : "border-transparent font-medium text-ink-2 hover:text-ink",
              )}
            >
              {panel.label}
            </button>
          ))}
        </div>
      )}
      {panels.map((panel, i) => (
        <div
          key={panel.id}
          id={`panel-${panel.id}`}
          role={hydrated ? "tabpanel" : undefined}
          aria-labelledby={hydrated ? `tab-${panel.id}` : undefined}
          hidden={hydrated && i !== selected}
          className={cn("pt-4", !hydrated && i > 0 && "mt-4 border-t border-line")}
        >
          {!hydrated && <h3 className="mb-2 text-base text-ink">{panel.label}</h3>}
          {panel.content}
        </div>
      ))}
    </div>
  );
}

/**
 * Text to copy as it is. Without JavaScript the text is still there to
 * select; the button only appears once it can work. `name` says what is
 * copied ("Copy User-Agent"); the outcome is announced through a separate
 * status, so the button's own name stays put.
 */
export function Snippet({ text, name }: { text: string; name: string }) {
  const hydrated = useHydrated();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <div className="relative mt-2.5 rounded-card border border-line bg-ground">
      <pre
        className={cn(
          "p-3 font-mono text-[13px] leading-relaxed break-all whitespace-pre-wrap text-ink",
          hydrated && "pr-24",
        )}
      >
        {text}
      </pre>
      {hydrated && (
        <>
          <button
            type="button"
            onClick={copy}
            aria-label={`Copy ${name}`}
            className="absolute top-1.5 right-1.5 min-h-11 rounded-control border-[1.5px] border-line-strong bg-surface px-3 text-[13px] font-semibold text-ink hover:border-ink-3 md:min-h-9"
          >
            <span aria-hidden="true">
              {state === "copied" ? "Copied" : state === "failed" ? "Select to copy" : "Copy"}
            </span>
          </button>
          <span role="status" className="sr-only">
            {state === "copied"
              ? `Copied ${name}`
              : state === "failed"
                ? `Could not copy ${name}; select it to copy`
                : ""}
          </span>
        </>
      )}
    </div>
  );
}

/**
 * The page's contents: a chip row on phones that scrolls inside itself (the
 * page never does), a rail from `lg`. With JavaScript, the section in view is
 * marked; without it, the links work all the same.
 */
export function Contents({ items }: { items: { href: string; label: string }[] }) {
  const [current, setCurrent] = useState<string | null>(null);
  const list = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setCurrent(`#${entry.target.id}`);
        }
      },
      { rootMargin: "-30% 0px -60% 0px" },
    );
    for (const { href } of items) {
      const section = document.getElementById(href.slice(1));
      if (section) observer.observe(section);
    }
    return () => observer.disconnect();
  }, [items]);

  useEffect(() => {
    // Keep the marked chip in view on a phone's scrolling row.
    if (!current || window.innerWidth >= 1024 || !list.current) return;
    const link = list.current.querySelector<HTMLAnchorElement>(`a[href="${current}"]`);
    if (link) list.current.scrollTo({ left: link.offsetLeft - 16, behavior: "smooth" });
  }, [current]);

  return (
    <nav
      aria-label="On this page"
      className="sticky top-0 z-20 -mx-4 border-b border-line bg-ground px-4 py-2 md:-mx-6 md:px-6 lg:top-6 lg:mx-0 lg:self-start lg:border-0 lg:bg-transparent lg:p-0"
    >
      <p className="mb-2 ml-3 hidden text-xs font-semibold tracking-wider text-ink-3 uppercase lg:block">
        On this page
      </p>
      <ol
        ref={list}
        className="flex [scrollbar-width:none] gap-1.5 overflow-x-auto lg:flex-col lg:gap-0 lg:overflow-visible"
      >
        {items.map(({ href, label }) => {
          const on = current === href;
          return (
            <li key={href} className="shrink-0">
              <a
                href={href}
                aria-current={on ? "true" : undefined}
                className={cn(
                  "inline-flex min-h-11 items-center rounded-full border px-3.5 text-sm whitespace-nowrap",
                  "lg:min-h-9 lg:rounded-none lg:border-0 lg:border-l-2 lg:bg-transparent lg:px-3",
                  on
                    ? "border-chip-on bg-chip-on text-chip-on-ink lg:border-action lg:font-semibold lg:text-ink"
                    : "border-line-strong bg-surface text-ink-2 hover:text-ink lg:border-line",
                )}
              >
                {label}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
