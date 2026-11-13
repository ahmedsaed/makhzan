# Phase B measurement: rule-based identifiers outside electronics

Data: production copy, ACTIVE listings only (61,134). Scripts and regexes: `kinds.py`, `cov.py`, `cov2.py`,
`fuzzy.py` in this directory. "Marketplace" = the one bespoke multi-vertical source (51% of all listings).
Other shops = "hobby shops" (6 WooCommerce/Odoo/Wix/Shopify electronics-leaning shops). Precision figures come from
me reading 25-32 random matches per code kind, so treat them as +/- 15 points. Counts are exact.

## 0. The finding that frames everything

Outside electronics and tools, nearly every department is one shop. Grouping needs two shops, so no identifier rule
can create a cross-shop group there. The cap is supply, not code extraction.

| dept | listings | shops | marketplace share | products | multi-shop products today | listings from non-marketplace shops |
|---|---|---|---|---|---|---|
| electronics | 29,293 | 9 | 2% | 27,940 | 889 (2,242 listings) | 28,459 |
| tools | 17,856 | 7 | 94% | 17,856 | 0 | 1,052 |
| seals-bearings | 7,901 | 1 | 100% | 7,901 | 0 | 0 |
| electrical | 1,316 | 3 | 97% | 1,316 | 0 | 31 |
| piping | 1,241 | 2 | 99% | 1,241 | 0 | 6 |
| chemicals | 1,037 | 6 | 75% | 1,037 | 0 | 252 |
| timber | 532 | 1 | 100% | 532 | 0 | 0 |
| machinery | 462 | 6 | 83% | 462 | 0 | 74 |
| welding / safety / garden / cleaning / rigging / security | 375/373/205/152/73/62 | 1 each | 100% | = listings | 0 | 0 |
| materials | 194 | 2 | 96% | 194 | 0 | 6 |
| automotive | 62 | 2 | 85% | 62 | 0 | 9 |

Maximum possible cross-shop pairing outside electronics: 1,052 + 252 + 74 + 31 + 6 + 6 + 9 = 1,430 listings, each
needing a marketplace (or other-shop) twin.

## 1. Code kinds, coverage, precision, payoff (all active listings of the department)

"Cross-shop groups" = a normalized code carried by listings from >= 2 different shops, today in different products
(every one I checked is in different products today: no identifier exists, so nothing merges).
"Est. correct" = my reading of those groups (before the existing title/value/form/same-shop vetoes, which would
remove some of the mixed ones).

| dept | code kind | match share | precision as identity | cross-shop groups | est. correct |
|---|---|---|---|---|---|
| tools | letter-led model code (`model2`, below) | 9% (1,662); 86% of hits are one brand family in the marketplace | ~90% (catalogue codes such as J58-210, E06-43-0180, ASR-6014, TU-501, SDL-8611) | 14 codes / 29 listings | 12 of 14 |
| tools | old broad "any letters+digits" token | 19% | ~15%: matches `6-in-1`, `5-inch`, `No.2`, `6Piece`, `3x140mm` | 33 codes | 12 (same real ones, buried in noise) |
| tools | `\d+ inch` size | 27% | ~0% (a size) | 26 codes / 2,673 listings | 0 |
| tools | `NxN` dims (generic) | 13% | ~0% (a size) | 35 codes / 149 listings | ~0 |
| tools | thread `M\d+x\d+` | 1% (134) | low: fastener size, many shops would share it legitimately | 0 | n/a |
| tools | screwdriver-style `NxN mm` (my "cable" regex) | 3% | 0%: it matched screwdriver sizes, real cable sections (`3x2.5mm²`, AWG) number 26 titles in three depts | 11 | 0 |
| seals-bearings | bearing designation (6204, 6205-2RS, UC310, NN3036) | 26% (2,063) | ~95% as a designation, but the suffix (open / ZZ / 2RS) changes the product | 0 (one shop) | n/a |
| seals-bearings | O-ring `ODxCS` | 38% (2,996) | ~95% (size is the identity for an O-ring) | 0 | n/a |
| seals-bearings | oil seal `IDxODxW` | 10% (827) | ~90% (profile letter A/AS/TC varies) | 0 | n/a |
| seals-bearings | uncovered by the three above | 26% (2,015) | oil cups, filters, packing styles, mechanical seals | - | - |
| electrical | letter-led model code | 9% (124 listings, 74 codes) | ~60% as product, ~100% as family (EZC250H appears at 100 A and 250 A, IK60N at 1P/2P/3P) | 0 | n/a |
| electrical | breaker rating + poles in title | 18% (232) | a rating, not an identity | 0 | n/a |
| piping | `\d+ inch` | 90% | ~0% (size) | 0 | n/a |
| piping | `class \d{3,4}` | 65% | ~0% (rating) | 0 | n/a |
| piping | `DN\d+` / `PN\d+` | <1% (10 / 2 titles) | n/a | 0 | n/a |
| piping | letter-led model code | 21% | 0%: the only code found is the standard "B16.20" | 0 | 0 |
| chemicals | brand + number (Loctite 574, Ambersil 5024A, Molykote 55) | 9% (96) | ~95%, but only the marketplace stocks these brands | 0 | n/a |
| chemicals | letter-led model code (GP-999, CP-0001, MD-50, A500) | 6% (61) | ~80% | 5 codes / 10 listings | 4 of 5 |
| machinery | letter-led model code | 5% (25) | ~85% (TKL-80, TWPS102, AAC1401) | 0 | n/a |
| welding | letter-led model code | 6% (23) | ~50% (MMA-160 vs MMA-250 are a family naming scheme) | 0 | n/a |
| automotive | letter-led model code | 19% (12) | ~90% (ELM327, MCP2551) but these are electronics parts | 0 | n/a |
| security | letter-led model code | 13% (8) | ~90% | 0 | n/a |
| timber | `NxNxN` dimensions | 80% | 0%: dimensions, timber is sold by species + size | 0 | n/a |
| safety, garden, cleaning, rigging, materials | letter-led model code | 0-15% | rare, mostly brand model numbers of a single listing | 0 | n/a |

Cross-domain note (seals-bearings): miniature bearings from the hobby shops are filed in electronics, and the
marketplace's bigger bearings in seals-bearings. A bearing designation present in both domains: 5 listings,
3 groups (61807, 6000, 6001, 51107, 51108). One conflicts: "6000ZZ shielded" vs plain "6000 Deep Groove". A suffix-aware key
is needed, and the group key is not domain-scoped today (`base_key`), so this would need a decision.

Within-shop repetition (no merge possible, same-shop veto): 356 of 1,331 bearing designations appear on more than one
marketplace listing (6205 vs 6205-2RS vs 6205-ZZ); 112 electrical listings share an exact title with another.
These are variant or duplicate-listing questions, not a Phase B matter.

### Regexes used (Python `re`, case-insensitive where noted)

```
N      = \d{1,4}(?:\.\d+)?          X = \s*[x*×X]\s*
model2 = (?<![\w.\-/])([A-Za-z]{1,6}[-.]?\d{2,}[A-Za-z0-9]{0,4}(?:[-./]\d{1,5}[A-Za-z0-9]{0,3}){0,2})(?![\w])
         then: strip [-. /], upper-case; drop if len<4, <2 digits, or it matches
         ^[A-Z]+\d+(MM|CM|W|V|A|KG|ML|M|G|L|HP|PCS|IN|KW|AH|BAR|MAH)$ ; drop a deny list:
         IP\d+ DC\d+ AC\d+ USB CAT\d RJ\d+ M\d{1,2} P\d{2,4} PH\d PZ\d SDS PPR PVC ISO DIN EN BS ASME ASTM NPT BSP
         GRI AISI SS\d{3} NO\d+ TYPE STYLE SIZE PN\d+ DN\d+ [A-Z]\d{1,2} GRADE K\d{1,2} RAL WD\d+ CR\d{3,4} AA AAA
         (CR\d{3,4} is in the deny list because CR-10 is a printer family, CR2032 is a battery: both family codes.)
bearing  = (?<![\w.\-/])((?:[1-9]\d{3,5}|[A-Z]{1,3}\d{3,5}))(?:[- ]?(?:2RS1?|2RSR?|ZZ|2Z|RS|Z|C[0-5]|N|NR|K))?(?![\w.])
           only when the title contains bearing|roller|ball; the suffix is matched but NOT in the key above (a real rule
           must put it in)
oring    = o[- ]?ring\s*(N)X(N)                       oilseal = oil\s*seal\s*(?:[A-Z]{1,6}-?[A-Z]*)?\s*(N)X(N)X(N)
brandnum = \b(loctite|ambersil|molykote|soudal|rust-?oleum|wd-?40|mechanic|amro|krylon|sikaflex|sika|dow ?corning)\s*(\d{2,5}[a-z]?)\b
thread   = \bM(\d{1,2})\s*[x*×]\s*(\d{1,3})\b          dn = \bDN\s?(\d{2,4})\b       cls = \bclass\s*(\d{3,4})\b
```

## 2. Example cross-shop groups (titles only)

Tools, correct (12 of 14):
- `ASR-5048 Beta Organizer-25` / `Beta Organizer-25 230x166x42.5mm ASR-5048`
- `Modular Monoblock Set with 12 Drawers ASR-6014` (x2 shops, identical title)
- `STEARNEL SDL-8611 Hot Air Gun 1800W ...` / `Hot Air Gun 220V 1800W SDL-8611 Digital Display ...`
- `M&R Screwdriver Set 5pcs MR-818` / `MR818 Screwdriver Set of 5 Pcs | MR`
- `TU-501 Cutting Pliers` / `TNI-U Wire Cutter - TU501 Side Snips` / `5 inch Wire Cutter "TNI-U TU-501"`
Tools, collisions: `Wire Stripper and Cutter YTH109` vs `YTH-109 Mini Flush Cut Plier 5 Inch` (different items, same code);
`BOX13` and `ORGANIZER25` came out of the old broad regex as "codes" (they are fragments of a name).
Chemicals, correct: `AMRO Super Glue GP999 20g` / `... GP999 20gr`; `RELIFE CP-0001 ... 50ml` / `RELIFE 50ML CP-0001 ...`;
`Md-50 Silicone Spray Oil Lubricant 400 Ml` / `SILICONE LUBRICANT MD-50`.
Chemicals, collision: `SMA A500 Quick Adhesive Gel 200ml` vs `SMA A500 Instant Adhesive 80gr with Activator 400mL`.

Code-free pairs I could find by fuzzy title similarity (Jaccard >= 0.6, different shops, no code): tools 128 pairs
(154 listings), chemicals 56 pairs (72 listings), zero in every other department. Of 14 random tools pairs, 3 were
the same product (`APT Heat Gun 2000W` / `Heat Gun 2000w Apt`; `Total Test Pencil 3x140mm` / `TOTAL Voltage Test Pencil
3x140mm`; the ASR-6014 pair). Wrong ones: same wattage different brand (`Total Heat Gun 2000W` vs `WISEUP Heat Gun 2000W`),
same product different size (`WD-40 Spray 100ml` vs `330mL`). So about 20% are real: ~25 tools, ~10-15 chemicals,
of which about 15 are already counted by the code groups above. No rule gets the rest; this is what an AI phase would
add, and it is small.

## 3. Shop-stated part numbers (`attributes->>'mfr_part_number'`)

| shop role | department | listings with MPN |
|---|---|---|
| hobby shop 1 (largest, 13.1k electronics) | electronics | 901 |
| hobby shop 2 | electronics | 1 |
| hobby shop 3 | electronics | 1 |
| everything else, every other department | | 0 |

- 903 listings (1.5%). Of those, only 73 equal the identifier the title extractor already finds, 801 have no
  identifier today, and 171 carry the MPN in the title. Most are passive-component manufacturer codes
  (`FRC0805J3R3 TS`, `CR0603JA0121G`, `0402CG100J500NT`) in titles like "Chip Resistor SMD 3.3Ω 0805".
- Cross-shop: only 8 MPN values are shared by 2+ of these listings, and only 10 of the 903 have their code in a title or
  identifier of another shop. All 10 (S8550, S9012-14, TL431, 1N4004/7, 74HC74, LL4148, SS210) already share an identifier
  today and sit in different products because the existing vetoes (form: SMD vs through-hole; title disagreement)
  declined. **New cross-shop groups from MPN: 0.** (SS210 is also a false match: a soldering tip `SS-210-K`.)
- Why zero: the other shops publish no MPN, and the MPN-bearing shop sells chip passives the other shops list by value.
  The MPN is useful as display and search data, not as a merge key, unless other shops start publishing theirs.
- The details stage has barely run (69 + 53 listings read), so MPN coverage may grow. Re-measure after it has.
- Related field: spec table key `Model` (1,527 listings: hobby shop 1 1,236, shop 2 181, shop 3 84, shop 4 23, ...,
  plus 56 in tools/chemicals/machinery). 785 have no identifier today. 25 values are shared across shops, 18 of them
  with no identifier on any member today (43 listings), but 13 of those 18 the title regex below finds anyway. Quality is
  mixed: `SPL-82`, `CP-22S`, `PCT-218`, `TU-501`, `XY-USB4`, `UT12A` are real; `A2212` (brushless motor at 1000KV and
  2200KV), `18650`, `401030` (cell sizes) are family or size codes. 396 no-identifier listings have a `Model` and no code in the
  title, which is where it adds something.

## 4. Electronics sanity

- Existing extractor (`makhzan_schemas.part_number.extract_part_number`, run over the copy): 9,042 of 29,293 get an
  identifier (31%); stored `part_number` matches (9,043). 20,251 get none (69%).
- Per shop with an identifier: hobby shops 22-43%, marketplace electronics 15%, one 3D shop 6%.
- Reading 45 no-identifier titles: the large majority are not parts with codes: chip passives by value
  (`Chip Resistor SMD 8.2Ω ±5% 0.125W 0805`), cables, tape, batteries, generic modules, tools. They would need a
  value+package normalizer or the AI phase, not an MPN rule. Not measured: how many cross-shop passive twins exist.
- **A real gap in the extractor:** two-to-six letters, optional hyphen, digits, as used by hobby-market brands
  (`CP-2015` solder wick, `PCT-218` and `PCT-223` WAGO-style connectors, `TB-1505` barrier block, `RL-084` / `RL-404`
  RELIFE tools, `KY-032` sensor, `HLK-10M24` PSU, `DT-830`, `DT-9205E`, `DSO-153`, `DPS-150`, `LS-00051`).
  Applying the `model2` regex to electronics listings that have no identifier today gives
  **235 cross-shop groups / 840 listings** (161 pairs of shops, 44 with three, 30 with four or more).
  Reading 49 of them (two samples): 16+16 clear and correct (~65%), 5+7 mixed (variants inside the code: `FC-26` male /
  female / angled, `SG-002` with different ranges, `RL-601S` Plus vs Mini, `R-48B` 30 W vs 40 W tip, `TQ-95` iron vs a tip that
  mentions it; the existing value-token and form vetoes would catch some), 4+3 wrong (`CR-10` printer vs an extruder kit
  "for CR-10", `AWG-16` gauge, `NEMA-42` frame size). Estimate: **~150 correct new groups (range 120-180)**, about 840 listings
  involved, against 889 multi-shop products today. This is the largest single gain I found, and it is not a new department.

## 5. Recommendation

Ranked by new correct cross-shop groups per unit of effort:

1. **Electronics: extend the extractor to letter-led hyphenated codes** (`model2`, with the deny list and
   `CR\d+`, `AWG`, `NEMA`, `RJ`, `CAT` excluded). ~150 groups (range 120-180), a code change in one profile, fully reversible
   with `make regroup-dry-run`. Add a "code is a family" guard before shipping: if a code is carried by listings of one
   shop that differ in a value token, do not treat it as a product identity (FC-26, RL-601S, R-48B). Keep every existing veto.
2. **Tools and chemicals: reuse the same `model2` rule**, because the same hobby-shop brands (ASR organizers, TNI-U, M&R,
   AMRO, RELIFE, SMA) appear in tools and chemicals as in electronics. ~16 correct groups (12 + 4, range 10-20).
   Cheap once item 1 exists; do not add the broad token regex (precision ~15%) and do not add any size regex.
3. **Shop-stated MPN / `Model` spec: low priority for merging** (0 new groups from MPN; ~5 from `Model`). Worth using
   as a fallback identifier where the title yields none (396 listings), subject to the family-code guard. Re-measure
   once the details stage has run on more shops.
4. **Seals-bearings: do not build rules yet.** The regexes work (bearing designation 26%, O-ring 38%, oil seal 10%, ~90-95%
   precise) but the department is one shop, so the payoff is 0 groups today. Revisit when a second bearing supplier is
   onboarded; the key must include the suffix (open / ZZ / 2RS) and the O-ring / oil-seal size, and the cross-domain
   case (miniature bearings filed in electronics) needs an explicit decision. Cost then is small.
5. **Electrical, piping, machinery, welding, security, automotive, materials, timber, safety, garden, cleaning, rigging:
   not worth rules.** One shop (or one shop plus <= 31 other listings); no cross-shop pair exists to find. Where codes
   exist they are family-level (Schneider EZC250H over several ratings) or specifications (inch, class, DN, dimensions).
   Do not spend effort here unless a second supplier is added, and for electrical (Schneider, Siemens, ABB codes)
   rules are cheap then.
6. **AI phase: only for what rules cannot reach, and it is small outside electronics.** Code-free same-product pairs
   outside electronics: ~10-25 in tools and chemicals combined (heat guns, WD-40, test pencils). In electronics the AI
   phase has real room: 69% have no identifier and most are chip passives, modules and accessories that need value
   normalization or description-level matching. That is where to size the AI phase, not the other 15 departments.

Honest uncertainty: the cross-shop counts are exact for these regexes on this snapshot; the "correct" shares come from
reading ~50 groups in electronics and all 14+5 in tools/chemicals; the electronics ~150 estimate has a +/- 30 range. I did
not run the real grouping pipeline, so interactions with the existing vetoes are estimated, not measured. The snapshot
will change as shops are re-crawled and new suppliers are added; item 4 and 5 verdicts flip if a second shop appears.
