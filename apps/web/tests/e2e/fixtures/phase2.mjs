/**
 * Stub payloads for the shop terms on the product page (docs/PRODUCT.md,
 * Phase 2), one product per case of the owner-approved mockup: options,
 * a minimum order with a stated part number, quantity prices, price on
 * request, "Fits" and "Ships from abroad"; and with several shops, mixed
 * minimums, some or all offers on request, a cheaper option at one shop,
 * quantity prices with a stale lowest, disagreeing part numbers, differing
 * "Fits", and a product mixing them all (TB6600).
 *
 * Shops are fictional (the mockup's names). Check dates are relative to when
 * the stub starts, so freshness tiers hold whatever day the suite runs.
 */

const DAY = 86_400_000;
const daysAgo = (days) => new Date(Date.now() - days * DAY).toISOString();

const shop = (slug, name, contact = null) => ({
  id: `sup-${slug}`,
  slug,
  name,
  name_ar: null,
  area: null,
  governorate: null,
  website_url: `https://${slug}.test`,
  contact,
});

const SPHINX = shop("sphinx-3d", "Sphinx 3D", {
  phone: "+201012345678",
  whatsapp: "+201012345678",
  email: null,
});
const CAIRO = shop("cairo-makers", "Cairo Makers", {
  phone: "+20223456789",
  whatsapp: null,
  email: "sales@cairo-makers.test",
});
const GIZA = shop("giza-robotics", "Giza Robotics", {
  phone: "+201122223333",
  whatsapp: "+201122223333",
  email: null,
});
const DELTA = shop("delta-components", "Delta Components", {
  phone: "+201234567890",
  whatsapp: null,
  email: null,
});
const NILE = shop("nile-parts-2", "Nile Parts", {
  phone: "+20233334444",
  whatsapp: null,
  email: null,
});
const BAZAAR = shop("bazaar-hub", "Bazaar Hub");
const ALEX = shop("alex-electronics", "Alex Electronics");
const MANS = shop("mansoura-electronics", "Mansoura Electronics");

const SHOPS = [SPHINX, CAIRO, GIZA, DELTA, NILE, BAZAAR, ALEX, MANS];

/** Shop terms default to what the API sends when a shop states none. */
function offer(id, supplier, title, price, stock, age, terms = {}) {
  return {
    brand: null,
    specs: {},
    documents: [],
    min_quantity: null,
    multiple_of: null,
    price_on_request: price === null,
    stock_quantity: null,
    variants: [],
    variants_checked_at: null,
    price_breaks: [],
    compatible_with: [],
    ships_from_abroad: null,
    mfr_part_number: null,
    videos: [],
    ...terms,
    id,
    title_en: title,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: `https://${supplier.slug}.test/p/${id}`,
    images: [],
    last_verified_at: daysAgo(age),
    supplier,
  };
}

const variant = (title, price, inStock, quantity = null) => ({
  title,
  price,
  in_stock: inStock,
  stock_quantity: quantity,
  sku: null,
});
const brk = (min_quantity, price) => ({ min_quantity, price });

const category = (domain, slug, name) => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en: name,
  name_ar: null,
});
const FILAMENT = category("3d-printing", "filament", "Filament");
const PRINTER_PARTS = category("3d-printing", "printer-parts", "Printer parts");
const RESISTORS = category("electronics", "resistors", "Resistors");
const POWER = category("electronics", "dc-dc-converters", "DC-DC converters");
const DRIVERS = category("electronics", "stepper-drivers", "Stepper drivers");
const ICS = category("electronics", "timers", "Timers");
const BOARDS = category("electronics", "esp32-boards", "ESP32 boards");
const SENSORS = category("electronics", "sensors", "Sensors");

function product(id, title, cat, offers, extra = {}) {
  const prices = offers.map((o) => o.price).filter((p) => p !== null);
  return {
    id,
    part_number: null,
    title_en: title,
    title_ar: null,
    brand: null,
    image: null,
    supplier_count: new Set(offers.map((o) => o.supplier.slug)).size,
    offer_count: offers.length,
    min_price: prices.length ? Math.min(...prices) : null,
    max_price: prices.length ? Math.max(...prices) : null,
    currency: "EGP",
    in_stock: offers.some((o) => o.stock_signal === "in_stock"),
    last_verified_at: offers[0].last_verified_at,
    category: cat,
    offers,
    ...extra,
  };
}

const YOUTUBE = (label, id) => ({ url: `https://www.youtube.com/watch?v=${id}`, label });

export const PHASE2 = {
  // One shop, six colours shown, two more behind "Show 2 more options"; one
  // costs more (the range), one has no price of its own ("see shop").
  "p2-options": product(
    "p2-options",
    "eSUN ASA+ 1.75mm 3D Filament 1KG",
    FILAMENT,
    [
      offer("o2-opt", SPHINX, "eSUN ASA+ 1.75mm 3D Filament 1KG", 1700, "in_stock", 2, {
        variants: [
          variant("Black", 1750, true),
          variant("Warm White", 1700, true),
          variant("Silver", 1700, true),
          variant("Blue", 1700, true),
          variant("Yellow", 1700, true),
          variant("Gray", null, true),
          variant("Red", 1700, false),
          variant("Orange", 1700, false),
        ],
        variants_checked_at: daysAgo(4),
        videos: [YOUTUBE("eSUN ASA+ print test", "asa-test")],
        specs: { Diameter: "1.75 mm", "Net weight": "1 kg" },
      }),
    ],
    { brand: "eSUN" },
  ),
  // Sold only in tens; the shop states the manufacturer's part number.
  "p2-minorder": product(
    "p2-minorder",
    "Chip Resistor SMD 680KΩ ±1% 100mW ±100ppm/℃ 0603",
    RESISTORS,
    [
      offer(
        "o2-min",
        CAIRO,
        "Chip Resistor SMD 680KΩ ±1 100mW ±100ppm/℃ 0603",
        0.15,
        "in_stock",
        4,
        {
          min_quantity: 10,
          multiple_of: 10,
          mfr_part_number: "FRC0603F6803TS",
        },
      ),
    ],
  ),
  "p2-breaks": product(
    "p2-breaks",
    "XL6009 DC-DC Step Up Boost Converter Module (3A)",
    POWER,
    [
      offer("o2-brk", GIZA, "XL6009 DC-DC Step UP Boost Converter Module (3A)", 47, "in_stock", 1, {
        price_breaks: [brk(10, 44), brk(50, 42)],
      }),
    ],
    { part_number: "XL6009" },
  ),
  "p2-por": product(
    "p2-por",
    "Creality K2 Plus Model Fan Assembly",
    PRINTER_PARTS,
    [
      offer("o2-por", SPHINX, "Creality K2 Plus Model Fan Assembly", null, "in_stock", 3, {
        compatible_with: ["K2 Plus"],
      }),
    ],
    { brand: "Creality" },
  ),
  "p2-badges": product(
    "p2-badges",
    "Premium Screen Protector for LCD Resin 3D Printers",
    PRINTER_PARTS,
    [
      offer(
        "o2-bdg",
        BAZAAR,
        "Premium Screen Protector for LCD 3D Printers (pack of 3)",
        180,
        "in_stock",
        5,
        {
          ships_from_abroad: true,
          compatible_with: [
            "ELEGOO Mars 4 Ultra",
            "ELEGOO Mars 5 Ultra",
            "ELEGOO Saturn 4 Ultra 12K",
            "ELEGOO Saturn 3 Ultra",
            "ELEGOO Jupiter SE",
            "ELEGOO Saturn 4 Ultra 16K",
            "Anycubic Photon M3",
            "Anycubic Photon Mono 4",
            "Anycubic Photon Mono 4 Ultra",
            "Anycubic M7 Max",
            "Anycubic M7 Pro",
            "Anycubic Photon Mono M5s",
            "Anycubic Photon Mono M5",
            "Anycubic Photon M3 Max",
            "Phrozen Sonic Mini 4K",
            "Anycubic Mono X 6K",
            "Phrozen Shuffle",
            "ELEGOO Mars 3",
            "ELEGOO Mars 3 Pro",
          ],
        },
      ),
    ],
  ),
  // Six shops on one real product: a stock count, quantity prices, options, a
  // stated part number, an out-of-stock and a stale offer that ships from abroad.
  "p2-multi": product(
    "p2-multi",
    "TB6600 Stepper Motor Driver 4A",
    DRIVERS,
    [
      offer("o2-tb-delta", DELTA, "TB6600 Stepper Motor Driver 4A 9-42V", 425, "in_stock", 3, {
        stock_quantity: 36,
      }),
      offer("o2-tb-giza", GIZA, "TB6600 Stepper Motor Driver 4A", 429, "in_stock", 1, {
        price_breaks: [brk(10, 415), brk(50, 405)],
      }),
      offer("o2-tb-nile", NILE, "TB6600 Stepper Driver 4.0A 42V", 430, "in_stock", 2),
      offer(
        "o2-tb-sphinx",
        SPHINX,
        "TB6600 Stepper Motor Driver (upgraded) 4A",
        550,
        "in_stock",
        4,
        {
          variants: [variant("Standard", 550, true), variant("With heatsink fan", 620, false)],
          variants_checked_at: daysAgo(4),
        },
      ),
      offer("o2-tb-cairo", CAIRO, "TB6600 Stepper Motor Driver 4A 9~42V", 435, "out_of_stock", 5, {
        mfr_part_number: "TB6600HG",
      }),
      offer("o2-tb-bazaar", BAZAAR, "TB6600 4A Stepper Driver Module", 504, "out_of_stock", 81, {
        ships_from_abroad: true,
      }),
    ],
    { part_number: "TB6600" },
  ),
  "p2-mixedmin": product("p2-mixedmin", "Carbon Film Resistor 1kΩ 0.25W Through Hole", RESISTORS, [
    offer("o2-mm-cairo", CAIRO, "Carbon Resistor 1KΩ 0.25W Through Hole", 0.15, "in_stock", 4, {
      min_quantity: 10,
      multiple_of: 10,
    }),
    offer("o2-mm-delta", DELTA, "Resistor 1K Ohm 1/4W", 1.25, "in_stock", 3),
    offer("o2-mm-nile", NILE, "1K Ohm Resistor 0.25W", 2, "in_stock", 2),
  ]),
  "p2-somepor": product(
    "p2-somepor",
    "Creality K1 / K1 Max Hotend Kit",
    PRINTER_PARTS,
    [
      offer("o2-sp-sphinx", SPHINX, "Creality K1 Hotend Kit (original)", null, "in_stock", 3),
      offer("o2-sp-giza", GIZA, "Creality K1 / K1 Max Hotend Kit", 1450, "in_stock", 1),
      offer("o2-sp-nile", NILE, "K1 Hotend Assembly Creality", 1500, "in_stock", 2),
      offer("o2-sp-bazaar", BAZAAR, "Creality K1 Hot End Kit 300°C", null, "out_of_stock", 6),
    ],
    { brand: "Creality" },
  ),
  "p2-allpor": product(
    "p2-allpor",
    "Anycubic Kobra 3 Combo 3D Printer",
    PRINTER_PARTS,
    [
      offer("o2-ap-sphinx", SPHINX, "Kobra 3 Combo Anycubic Egypt", null, "in_stock", 3),
      offer("o2-ap-giza", GIZA, "Anycubic Kobra 3 Combo (4-colour)", null, "in_stock", 1),
      offer(
        "o2-ap-bazaar",
        BAZAAR,
        "Anycubic Kobra 3 Combo Multicolour 3D Printer",
        null,
        "out_of_stock",
        6,
      ),
    ],
    { brand: "Anycubic" },
  ),
  "p2-cheapopt": product(
    "p2-cheapopt",
    "ESP32-S 38Pin Development Board (WiFi and Bluetooth)",
    BOARDS,
    [
      offer(
        "o2-co-nile",
        NILE,
        "ESP32 38 Pin Development Board WiFi + Bluetooth",
        340,
        "in_stock",
        2,
      ),
      offer(
        "o2-co-delta",
        DELTA,
        "ESP32-S 38Pin Development Board (WIFI and Bluetooth)",
        355,
        "in_stock",
        3,
      ),
      offer("o2-co-cairo", CAIRO, "ESP32 DevKit 38 Pin (CP2102)", 360, "in_stock", 4, {
        variants: [
          variant("Soldered headers", 360, true),
          variant("Without headers", 320, true),
          variant("Type-C version", 380, false),
        ],
        variants_checked_at: daysAgo(4),
      }),
    ],
    { part_number: "ESP32" },
  ),
  "p2-volume": product(
    "p2-volume",
    "LM2596 DC-DC Adjustable Step-Down Converter (3A)",
    POWER,
    [
      offer(
        "o2-v-giza",
        GIZA,
        "LM2596 DC-DC Adjustable Step-Down Converter (3A)",
        55,
        "in_stock",
        1,
        {
          price_breaks: [brk(20, 45), brk(50, 40), brk(100, 35)],
        },
      ),
      offer("o2-v-delta", DELTA, "LM2596 Buck Converter Module 3A", 65, "in_stock", 3, {
        stock_quantity: 74,
      }),
      offer("o2-v-cairo", CAIRO, "LM2596S DC-DC Step Down Module", 90, "in_stock", 4),
      offer("o2-v-alex", ALEX, "LM2596 Step-Down Power Module", 80, "out_of_stock", 2),
      offer("o2-v-mans", MANS, "LM2596 DC to DC buck converter", 48, "in_stock", 81),
    ],
    { part_number: "LM2596" },
  ),
  "p2-mfrs": product(
    "p2-mfrs",
    "NE555 Precision Timer IC DIP-8",
    ICS,
    [
      offer("o2-mf-cairo", CAIRO, "NE555P Timer IC DIP-8", 5.5, "in_stock", 4, {
        mfr_part_number: "NE555P",
      }),
      offer("o2-mf-delta", DELTA, "NE555 Single Timer IC", 6, "in_stock", 3, {
        mfr_part_number: "NE555",
      }),
      offer("o2-mf-nile", NILE, "555 Timer IC (NE555)", 7.5, "in_stock", 2),
    ],
    { part_number: "NE555" },
  ),
  "p2-fits": product(
    "p2-fits",
    "MK8 Brass Nozzle 0.4mm (1.75mm filament)",
    PRINTER_PARTS,
    [
      offer("o2-f-bazaar", BAZAAR, "MK8 Brass Nozzle 0.4mm M6", 15, "in_stock", 5, {
        ships_from_abroad: true,
      }),
      offer("o2-f-giza", GIZA, "MK8 Nozzle 0.4mm Brass", 20, "in_stock", 1, {
        compatible_with: ["Ender 3", "Anet A8"],
      }),
      offer("o2-f-sphinx", SPHINX, "MK8 Brass Nozzle 0.4 for Creality", 25, "in_stock", 2, {
        compatible_with: ["Ender 3", "Ender 3 V2", "Ender 5", "CR-10"],
      }),
      offer("o2-f-delta", DELTA, "3D Printer Nozzle MK8 0.4mm", 30, "in_stock", 3),
    ],
    { part_number: "MK8" },
  ),
  "p2-histmulti": product(
    "p2-histmulti",
    "XY-MD02 SHT20 Temperature & Humidity Sensor (RS485 Modbus)",
    SENSORS,
    [
      offer("o2-h-delta", DELTA, "XY-MD02 Temperature Humidity Sensor RS485", 320, "in_stock", 3),
      offer("o2-h-nile", NILE, "SHT20 Modbus RS485 Sensor XY-MD02", 335, "in_stock", 2),
      offer("o2-h-giza", GIZA, "XY-MD02 SHT20 Sensor Module", 345, "out_of_stock", 1),
    ],
    { part_number: "XY-MD02" },
  ),
};

/** The lead offer's words, so "What the shops say" has a panel. */
const DESCRIPTIONS = {
  "o2-opt":
    "eSUN ASA+ is a UV- and weather-resistant engineering filament for outdoor parts. Print at 240–260 °C with a heated bed at 90–110 °C; an enclosure is recommended.",
  "o2-min": "Thick film chip resistor, 0603 package, 680 kΩ, 1% tolerance, rated 100 mW.",
  "o2-brk":
    "Adjustable boost converter based on the XL6009. Input 3–32 V, output 5–35 V, up to 3 A switch current.",
  "o2-por": "Original replacement part-cooling fan assembly for the Creality K2 Plus, with cable.",
  "o2-bdg": "Tempered protective film for the LCD of resin printers. Three sheets per pack.",
  "o2-tb-delta":
    "TB6600 single-axis stepper driver for two-phase motors up to 4 A. Microstepping to 1/32, opto-isolated inputs, 9–42 V DC supply.",
};

/** `[status, body]` for a path this fixture owns, or null. */
export function phase2Fixture(path) {
  const productId = path.match(/^\/products\/([^/]+)$/)?.[1];
  if (productId && PHASE2[productId]) return [200, PHASE2[productId]];
  const similar = path.match(/^\/products\/([^/]+)\/similar$/)?.[1];
  if (similar && PHASE2[similar]) return [200, []];

  const listingId = path.match(/^\/listings\/([^/]+)$/)?.[1];
  for (const item of Object.values(PHASE2)) {
    const found = item.offers.find((o) => o.id === listingId);
    if (found) {
      return [
        200,
        {
          ...found,
          product_id: item.id,
          description_en: DESCRIPTIONS[found.id] ?? null,
          description_ar: null,
          part_number: item.part_number,
          unit: null,
          status: "active",
          category: item.category,
        },
      ];
    }
  }

  const slug = path.match(/^\/suppliers\/([^/]+)$/)?.[1];
  const supplier = SHOPS.find((s) => s.slug === slug);
  if (supplier) {
    const reach = supplier.contact;
    return [
      200,
      {
        ...supplier,
        listing_count: 1761,
        in_stock_count: 1200,
        last_verified_at: daysAgo(1),
        domains: [],
        top_categories: [],
        contact: reach && {
          phones: reach.phone ? [reach.phone] : [],
          whatsapp: reach.whatsapp,
          email: reach.email,
          address: null,
          area: null,
          governorate: null,
          maps_url: null,
          opening_hours: ["Sa,Su,Mo,Tu,We,Th 11:00-21:00"],
          branches: [],
          sources: [],
        },
      },
    ];
  }
  return null;
}
