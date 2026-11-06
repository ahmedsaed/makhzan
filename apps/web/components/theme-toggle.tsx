"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "system", label: "Device", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
] as const;

const noop = () => () => {};

/**
 * Light and dark follow the device; this overrides it, and "Device" hands the
 * choice back — a two-way toggle would strand anyone who touched it on a fixed
 * theme forever.
 *
 * The chosen option is only marked after hydration: the server cannot know a
 * stored preference, and marking "Device" there would flash the wrong one.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const hydrated = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );

  return (
    <div
      role="group"
      aria-label="Theme"
      className={cn("flex overflow-hidden rounded-full border border-line-strong", className)}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = hydrated && (theme ?? "system") === value;
        return (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={hydrated ? active : undefined}
            title={label}
            onClick={() => setTheme(value)}
            className={cn(
              "grid size-11 place-items-center sm:size-9",
              active ? "bg-chip-on text-chip-on-ink" : "text-ink-2 hover:text-ink",
            )}
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        );
      })}
    </div>
  );
}
