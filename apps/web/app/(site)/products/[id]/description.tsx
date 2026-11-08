/**
 * A shop's own description, shown in full: no clamp and no "Read more". Its
 * length cannot hide anything that matters: on a phone the price or offers
 * come before it and the bottom bar keeps the way to the shop on screen; on a
 * wide screen they sit beside it.
 *
 * Supplier prose, shown as written and never translated; `dir="auto"` for the
 * few that are in Arabic.
 */
export function Description({ heading, text }: { heading: string; text: string }) {
  return (
    <section data-description className="mt-6 lg:mt-5">
      <h2 className="text-[15px]">{heading}</h2>
      <p dir="auto" className="mt-1.5 text-sm leading-relaxed whitespace-pre-line text-ink-2">
        {text}
      </p>
    </section>
  );
}
