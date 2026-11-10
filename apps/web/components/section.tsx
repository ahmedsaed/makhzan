import { cn } from "@/lib/utils";

/** Page shell: one max width and one gutter, applied in exactly one place. */
export function Container({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("mx-auto w-full max-w-7xl px-4 md:px-6", className)}>{children}</div>;
}

export function SectionHeading({
  children,
  className,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <h2 id={id} className={cn("mb-3 text-lg text-ink", className)}>
      {children}
    </h2>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-card border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="font-display text-base font-bold text-ink">{title}</p>
      {hint && <p className="mt-1 text-sm text-ink-2">{hint}</p>}
    </div>
  );
}
