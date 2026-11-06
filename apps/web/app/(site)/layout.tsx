import { SiteHeader } from "@/components/site-header";

/** Every page but home: the full header, search included. A route group, so it
 *  adds nothing to the URL. */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">{children}</main>
    </>
  );
}
