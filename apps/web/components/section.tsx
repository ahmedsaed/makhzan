import { cn } from "@/lib/utils";

/** Page shell: one max width and one gutter, applied in exactly one place. */
export function Container({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("mx-auto w-full max-w-6xl px-4", className)}>{children}</div>;
}

export function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 font-display text-lg font-bold text-ink">{children}</h2>;
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border-2 border-dashed border-rule px-6 py-12 text-center">
      <p className="font-display text-base font-bold text-ink">{title}</p>
      {hint && <p className="mt-1 text-sm text-ink-muted">{hint}</p>}
    </div>
  );
}
