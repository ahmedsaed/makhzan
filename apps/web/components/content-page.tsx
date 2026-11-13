import { Prose } from "@/components/prose";
import { Container } from "@/components/section";
import type { Rich } from "@/lib/content/prose";
import { cn } from "@/lib/utils";

/**
 * The shell of the site's reading pages (/about, /faq, /contact, /terms), as
 * /privacy lays itself out: one narrow column, an h1, then h2 sections.
 */
export function ContentPage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl sm:text-3xl">{title}</h1>
      {children}
    </Container>
  );
}

export function Paragraph({ parts, className }: { parts: Rich; className?: string }) {
  return (
    <p className={cn("mt-3 text-[15px] leading-relaxed text-ink-2", className)}>
      <Prose parts={parts} />
    </p>
  );
}

/** A section with its heading, linkable by `id`. */
export function ContentSection({
  id,
  title,
  children,
  className,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className={cn("mt-8 scroll-mt-20", className)}
    >
      <h2 id={`${id}-heading`} className="text-lg text-ink">
        {title}
      </h2>
      {children}
    </section>
  );
}
