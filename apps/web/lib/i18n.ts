/**
 * Bilingual UI strings, resolved on the server from the route segment.
 *
 * Language is a URL, not React state. The previous app kept it in a context
 * that defaulted to English and was corrected in an effect, so the server always
 * emitted `<html lang="en">`, an Arabic page could not be linked or indexed, and
 * the choice reset on reload. Here `/en/…` and `/ar/…` are separate routes and
 * the dictionary is picked before render.
 *
 * Only chrome is translated. Product titles, descriptions and supplier names are
 * shown as the supplier published them — a listing is evidence about a shop, and
 * translating it would misrepresent what is on the shelf.
 */

export const LANGS = ["en", "ar"] as const;
export type Lang = (typeof LANGS)[number];

export const DEFAULT_LANG: Lang = "en";

export function isLang(value: string | undefined): value is Lang {
  return value === "en" || value === "ar";
}

/** Text direction for a language. Drives `dir` on `<html>`; nothing else. */
export function dirOf(lang: Lang): "ltr" | "rtl" {
  return lang === "ar" ? "rtl" : "ltr";
}

/** BCP-47 tag for Intl formatting. Egypt-specific, so numerals and currency
 *  render the way a buyer in Cairo expects. */
export function localeOf(lang: Lang): string {
  return lang === "ar" ? "ar-EG" : "en-EG";
}

export type Dictionary = {
  brand: string;
  tagline: string;
  heroLead: string;
  searchPlaceholder: string;
  searchExamples: string;
  searchAction: string;
  browse: string;
  browseAll: string;
  allVerticals: string;
  byTrade: string;
  multiSupplier: string;
  multiSupplierLead: string;
  statProducts: string;
  statSuppliers: string;
  statVerticals: string;

  results: string;
  noResults: string;
  noResultsHint: string;
  filters: string;
  clearAll: string;
  showResults: string;
  sort: string;
  sortRelevance: string;
  sortPriceAsc: string;
  sortPriceDesc: string;
  sortSuppliers: string;
  sortVerified: string;
  facetTrade: string;
  facetCategory: string;
  facetAvailability: string;
  inStockOnly: string;
  identifierBand: string;

  from: string;
  suppliersCount: string;
  offers: string;
  priceRange: string;
  priceOnRequest: string;
  visitSupplier: string;
  visitNamed: string;
  notSoldHere: string;
  alsoAt: string;
  related: string;
  relatedWip: string;
  seeOtherOffers: string;
  description: string;
  descriptionSource: string;
  partNumber: string;
  brandLabel: string;
  category: string;
  verified: string;
  noPhoto: string;

  inStock: string;
  outOfStock: string;
  lowStock: string;
  madeToOrder: string;
  unknownStock: string;

  supplierListings: string;
  area: string;
  governorate: string;
  visitWebsite: string;
  lastSwept: string;

  withdrawn: string;
  withdrawnHint: string;
  notFound: string;
  notFoundHint: string;
  backHome: string;

  language: string;
  theme: string;
  footerCatalogue: string;
  footerSuppliers: string;
  footerAbout: string;
  howItWorks: string;
  freshness: string;
  handoffNote: string;
  /** Precedes the studio's name, which is linked and not translated. */
  madeBy: string;
};

const en: Dictionary = {
  brand: "makhzan",
  tagline: "Find a part across Egypt's suppliers",
  heroLead: "One search across every supplier catalogue we track.",
  searchPlaceholder: "Part number, name, or brand",
  searchExamples: "LM358, ESP32, 0805 resistor…",
  searchAction: "Search",
  browse: "Browse",
  browseAll: "All trades",
  allVerticals: "All trades",
  byTrade: "Browse by trade",
  multiSupplier: "Sold by more than one supplier",
  multiSupplierLead: "The only place you can see these side by side.",
  statProducts: "products",
  statSuppliers: "suppliers",
  statVerticals: "trades",

  results: "products",
  noResults: "Nothing matched",
  noResultsHint: "Try the part number on its own, or drop a filter.",
  filters: "Filters",
  clearAll: "Clear all",
  showResults: "Show results",
  sort: "Sort",
  sortRelevance: "Best match",
  sortPriceAsc: "Price: low to high",
  sortPriceDesc: "Price: high to low",
  sortSuppliers: "Most suppliers",
  sortVerified: "Recently verified",
  facetTrade: "Trade",
  facetCategory: "Category",
  facetAvailability: "Availability",
  inStockOnly: "In stock only",
  identifierBand: "Looks like a part number — ranked by identifier match first.",

  from: "from",
  suppliersCount: "suppliers",
  offers: "offers",
  priceRange: "Price range",
  priceOnRequest: "Price on request",
  visitSupplier: "Visit supplier",
  visitNamed: "Visit",
  notSoldHere: "makhzan doesn't sell — every offer opens the supplier's own site.",
  alsoAt: "also at",
  related: "Related products",
  relatedWip: "Work in progress — these suggestions are not reliable yet.",
  seeOtherOffers: "See other suppliers",
  description: "Description",
  descriptionSource: "From the supplier's page.",
  partNumber: "Part number",
  brandLabel: "Brand",
  category: "Category",
  verified: "Verified",
  noPhoto: "No photo",

  inStock: "In stock",
  outOfStock: "Out of stock",
  lowStock: "Low stock",
  madeToOrder: "Made to order",
  unknownStock: "Availability unknown",

  supplierListings: "active listings",
  area: "Area",
  governorate: "Governorate",
  visitWebsite: "Visit shop website",
  lastSwept: "Last checked",

  withdrawn: "This listing was withdrawn",
  withdrawnHint: "The supplier no longer lists it. Other suppliers may still have it.",
  notFound: "Not found",
  notFoundHint: "That page doesn't exist, or the listing has been removed.",
  backHome: "Back to search",

  language: "Language",
  theme: "Theme",
  footerCatalogue: "Catalogue",
  footerSuppliers: "Suppliers",
  footerAbout: "About",
  howItWorks: "How makhzan works",
  freshness: "How we collect this",
  handoffNote: "makhzan is a directory. Buying happens on the supplier's own site.",
  madeBy: "makhzan is made by",
};

const ar: Dictionary = {
  brand: "مخزن",
  tagline: "ابحث عن قطعة لدى موردي مصر",
  heroLead: "بحث واحد في كل كتالوجات الموردين التي نتابعها.",
  searchPlaceholder: "رقم القطعة أو الاسم أو الماركة",
  searchExamples: "LM358، ESP32، مقاومة 0805…",
  searchAction: "بحث",
  browse: "تصفح",
  browseAll: "كل المجالات",
  allVerticals: "كل المجالات",
  byTrade: "تصفح حسب المجال",
  multiSupplier: "متوفر لدى أكثر من مورد",
  multiSupplierLead: "المكان الوحيد الذي تقارنها فيه جنبًا إلى جنب.",
  statProducts: "منتج",
  statSuppliers: "مورد",
  statVerticals: "مجال",

  results: "منتج",
  noResults: "لا توجد نتائج",
  noResultsHint: "جرّب رقم القطعة وحده، أو أزل أحد عوامل التصفية.",
  filters: "تصفية",
  clearAll: "مسح الكل",
  showResults: "عرض النتائج",
  sort: "ترتيب",
  sortRelevance: "الأنسب",
  sortPriceAsc: "السعر: من الأقل",
  sortPriceDesc: "السعر: من الأعلى",
  sortSuppliers: "الأكثر موردين",
  sortVerified: "الأحدث تحققًا",
  facetTrade: "المجال",
  facetCategory: "الفئة",
  facetAvailability: "التوفر",
  inStockOnly: "المتوفر فقط",
  identifierBand: "يبدو أنه رقم قطعة — الترتيب حسب مطابقة الرقم أولًا.",

  from: "يبدأ من",
  suppliersCount: "موردين",
  offers: "عروض",
  priceRange: "نطاق السعر",
  priceOnRequest: "السعر عند الطلب",
  visitSupplier: "عرض لدى المورد",
  visitNamed: "عرض",
  notSoldHere: "مخزن لا يبيع — كل عرض يفتح موقع المورد نفسه.",
  alsoAt: "متوفر أيضًا لدى",
  related: "منتجات ذات صلة",
  relatedWip: "قيد التطوير — هذه الاقتراحات غير دقيقة بعد.",
  seeOtherOffers: "عرض موردين آخرين",
  description: "الوصف",
  descriptionSource: "من صفحة المورد.",
  partNumber: "رقم القطعة",
  brandLabel: "الماركة",
  category: "الفئة",
  verified: "تم التحقق",
  noPhoto: "لا توجد صورة",

  inStock: "متوفر",
  outOfStock: "غير متوفر",
  lowStock: "كمية محدودة",
  madeToOrder: "حسب الطلب",
  unknownStock: "التوفر غير معروف",

  supplierListings: "منتج معروض",
  area: "المنطقة",
  governorate: "المحافظة",
  visitWebsite: "زيارة موقع المتجر",
  lastSwept: "آخر تحديث",

  withdrawn: "تم سحب هذا العرض",
  withdrawnHint: "لم يعد المورد يعرضه. قد يتوفر لدى موردين آخرين.",
  notFound: "غير موجود",
  notFoundHint: "هذه الصفحة غير موجودة، أو تم حذف العرض.",
  backHome: "العودة إلى البحث",

  language: "اللغة",
  theme: "المظهر",
  footerCatalogue: "الكتالوج",
  footerSuppliers: "الموردون",
  footerAbout: "عن مخزن",
  howItWorks: "كيف يعمل مخزن",
  freshness: "كيف نجمع البيانات",
  handoffNote: "مخزن دليل للموردين. الشراء يتم على موقع المورد نفسه.",
  madeBy: "مخزن من صنع",
};

const DICTIONARIES: Record<Lang, Dictionary> = { en, ar };

export function getDictionary(lang: Lang): Dictionary {
  return DICTIONARIES[lang];
}

/**
 * Pick a language from an Accept-Language header.
 *
 * Deliberately crude: with two languages, whichever is named first wins, and
 * anything else falls back to English. Quality values would add precision that
 * cannot change the answer.
 */
export function preferredLang(acceptLanguage: string | null | undefined): Lang {
  for (const tag of (acceptLanguage ?? "").split(",")) {
    const code = tag.trim().slice(0, 2).toLowerCase();
    if (code === "ar") return "ar";
    if (code === "en") return "en";
  }
  return DEFAULT_LANG;
}
