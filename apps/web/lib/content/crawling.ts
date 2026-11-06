/**
 * Long-form copy for the "how we collect this" page.
 *
 * Kept out of lib/i18n.ts on purpose: that dictionary is short interface labels,
 * and mixing paragraphs into it makes both harder to maintain.
 *
 * This page exists because publishing an aggregator invites the question, and
 * the honest answer here is a good one. It is also the page to point a supplier
 * at when they ask what we are doing — so it has to be accurate, not
 * aspirational. If any of it stops being true, change the crawler or change the
 * page.
 */

import type { Lang } from "@/lib/i18n";

export type CrawlingSection = { heading: string; body: string[] };

export type CrawlingContent = {
  title: string;
  lead: string;
  sections: CrawlingSection[];
  contactHeading: string;
  contactBody: string;
  contactEmail: string;
};

const CONTACT_EMAIL = "crawler@makhzan.eg";

const en: CrawlingContent = {
  title: "How we collect this",
  lead: "makhzan is a directory. It shows what Egyptian suppliers publish and sends you to them to buy. Nothing is sold here, and no supplier pays to appear.",
  sections: [
    {
      heading: "What we read",
      body: [
        "Only the public catalogue pages and product APIs a shop already serves to any visitor — the same data you would see browsing the site yourself.",
        "We do not create accounts, log in, place orders, or read anything behind a login. We do not collect anything about a supplier's customers.",
      ],
    },
    {
      heading: "We follow what each site publishes",
      body: [
        "Before fetching anything we read the site's robots.txt and obey it. A path a shop asks us not to read is not read.",
        "If a site sets Crawl-delay, we treat it as a floor rather than a target: a shop asking for 20 seconds between requests gets 20, even though our own default is longer than most crawlers use.",
      ],
    },
    {
      heading: "We go slowly on purpose",
      body: [
        "One request at a time per shop, with a pause of at least 15 seconds between them. A full pass over a supplier's catalogue is spread across about a week rather than run in one burst, so no shop sees a spike of traffic from us.",
        "Our crawler identifies itself in every request and gives an address to write to, so anyone looking at their server logs can tell who we are.",
      ],
    },
    {
      heading: "Prices here may be out of date",
      body: [
        "Every listing shows when we last checked it. We do not control supplier pricing and cannot guarantee a price is still current — always confirm on the supplier's own site before buying.",
        "If a supplier stops listing something, it drops out of makhzan after a full pass confirms it is gone.",
      ],
    },
    {
      heading: "If you are a supplier",
      body: [
        "We would rather have your permission than work around its absence. If you would like to be removed, listed differently, crawled more slowly, or crawled at a particular hour, write to us and we will do it.",
        "If you would like to be listed and are not yet, that is easier still.",
      ],
    },
  ],
  contactHeading: "Contact",
  contactBody: "Questions, corrections, or a request to change how we crawl your site:",
  contactEmail: CONTACT_EMAIL,
};

const ar: CrawlingContent = {
  title: "كيف نجمع هذه البيانات",
  lead: "مخزن دليل للموردين. يعرض ما ينشره الموردون في مصر ثم يحيلك إليهم للشراء. لا نبيع شيئًا هنا، ولا يدفع أي مورد مقابل الظهور.",
  sections: [
    {
      heading: "ماذا نقرأ",
      body: [
        "فقط صفحات الكتالوج العامة وواجهات المنتجات التي يتيحها المتجر لأي زائر — نفس البيانات التي ستراها لو تصفحت الموقع بنفسك.",
        "لا ننشئ حسابات، ولا نسجّل الدخول، ولا نضع طلبات، ولا نقرأ أي شيء خلف تسجيل الدخول. ولا نجمع أي بيانات عن عملاء المورد.",
      ],
    },
    {
      heading: "نلتزم بما ينشره كل موقع",
      body: [
        "قبل أي طلب نقرأ ملف robots.txt الخاص بالموقع ونلتزم به. أي مسار يطلب المتجر عدم قراءته لا نقرأه.",
        "وإذا حدّد الموقع مدة انتظار بين الطلبات (Crawl-delay) نعتبرها حدًا أدنى لا هدفًا: متجر يطلب ٢٠ ثانية يحصل على ٢٠ ثانية.",
      ],
    },
    {
      heading: "نتحرك ببطء عن قصد",
      body: [
        "طلب واحد في كل مرة لكل متجر، وبفاصل لا يقل عن ١٥ ثانية. ونوزّع المسح الكامل لكتالوج المورد على أسبوع تقريبًا بدلًا من تنفيذه دفعة واحدة، حتى لا يرى أي متجر ضغطًا مفاجئًا منّا.",
        "ويعرّف الزاحف عن نفسه في كل طلب ويترك عنوانًا للتواصل، حتى يعرف من يطالع سجلات خادمه من نحن.",
      ],
    },
    {
      heading: "قد تكون الأسعار هنا قديمة",
      body: [
        "كل عرض يوضّح آخر مرة تحققنا فيها منه. نحن لا نتحكم في أسعار الموردين ولا نضمن أن السعر ما زال ساريًا — تأكّد دائمًا من موقع المورد قبل الشراء.",
        "وإذا توقف مورد عن عرض منتج، يختفي من مخزن بعد أن يؤكد مسح كامل أنه لم يعد موجودًا.",
      ],
    },
    {
      heading: "إذا كنت موردًا",
      body: [
        "نفضّل أن نحصل على موافقتك بدلًا من العمل بدونها. إن أردت إزالة متجرك، أو عرضه بشكل مختلف، أو مسحه بوتيرة أبطأ، أو في ساعة معيّنة، راسلنا وسننفّذ ذلك.",
        "وإن أردت أن تُدرج ولم تُدرج بعد، فهذا أسهل.",
      ],
    },
  ],
  contactHeading: "للتواصل",
  contactBody: "لأي سؤال أو تصحيح أو طلب بتغيير طريقة مسح موقعك:",
  contactEmail: CONTACT_EMAIL,
};

const CONTENT: Record<Lang, CrawlingContent> = { en, ar };

export function getCrawlingContent(lang: Lang): CrawlingContent {
  return CONTENT[lang];
}
