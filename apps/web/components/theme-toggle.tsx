"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

/**
 * Same shell as every other header control, so the row lines up. Swapping the
 * icon via the `dark` class rather than mounted state avoids a flash and keeps
 * this renderable on the server.
 */
export function ThemeToggle({ label }: { label: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-rule text-ink-muted hover:bg-chip hover:text-ink"
    >
      <Sun className="hidden size-4 dark:block" />
      <Moon className="block size-4 dark:hidden" />
    </button>
  );
}
