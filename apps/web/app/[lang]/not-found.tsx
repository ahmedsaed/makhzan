import { Link } from "@/components/link";

import { Container } from "@/components/section";
import { getDictionary } from "@/lib/i18n";

/** Language is not available to a not-found boundary, so this answers in
 *  English — the default the middleware also picks. */
export default function NotFound() {
  const t = getDictionary("en");
  return (
    <Container className="py-20 text-center">
      <h1 className="text-2xl">{t.notFound}</h1>
      <p className="mt-2 text-sm text-ink-muted">{t.notFoundHint}</p>
      <Link
        href="/en"
        className="mt-6 inline-block rounded-lg border-2 border-accent bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink"
      >
        {t.backHome}
      </Link>
    </Container>
  );
}
