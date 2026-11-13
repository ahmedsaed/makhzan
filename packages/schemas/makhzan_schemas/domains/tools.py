"""The tools & equipment vertical.

makhzan's second domain, and the first authored rather than inherited from the
original electronics build. It exists to be mapped *onto*: one marketplace alone
publishes ~300 leaf categories under Tools & Accessories, which is far too
granular to browse. This tree is deliberately coarse — a few dozen leaves that a
buyer would actually navigate — and source categories are mapped onto it through
a crosswalk (see `crosswalks/`), not inferred from product titles.

Identifiers: a letter-led catalogue code (ASR-6014, TU-501, SDL-8611, MR818),
measured at about 90% precise as an identity in this department. It is
family-checked — brands do reuse a code across a range, and once one shop lists
several products under it, it stops being used — and every merge still needs
the titles to agree. Sizes ("5 inch", "3x140mm"), threads and the broad
letters-and-digits token are deliberately not read: they are never identity.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile
from makhzan_schemas.identifiers import model_code

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    # Groups
    ("hand-tools", "Hand Tools", "أدوات يدوية", None),
    ("power-tools", "Power Tools", "أدوات كهربائية", None),
    ("measurement", "Measurement & Layout", "القياس والتخطيط", None),
    ("tool-consumables", "Accessories & Consumables", "ملحقات ومستهلكات", None),
    ("pneumatic", "Pneumatic & Air", "أدوات هوائية", None),
    # Hand tools
    ("wrenches", "Wrenches & Spanners", "مفاتيح ربط", "hand-tools"),
    ("sockets-drivers", "Sockets & Drivers", "أطقم بوكس", "hand-tools"),
    ("pliers", "Pliers & Grips", "زرديات وكماشات", "hand-tools"),
    ("screwdrivers", "Screwdrivers & Hex Keys", "مفكات ومفاتيح ألن", "hand-tools"),
    ("hammers", "Hammers & Striking", "شواكيش وأدوات طرق", "hand-tools"),
    ("cutting-hand", "Hand Cutting Tools", "أدوات قص يدوية", "hand-tools"),
    ("clamps-vises", "Clamps & Vises", "ملازم ومشابك", "hand-tools"),
    ("painting-tools", "Painting & Surface Tools", "أدوات الدهان والأسطح", "hand-tools"),
    ("automotive-tools", "Automotive Tools", "أدوات السيارات", "hand-tools"),
    ("hand-tools-other", "Other Hand Tools", "أدوات يدوية أخرى", "hand-tools"),
    # Power tools
    ("drills", "Drills & Drivers", "شنيور ومفكات كهربائية", "power-tools"),
    ("saws", "Saws", "مناشير", "power-tools"),
    ("grinders", "Grinders & Cutters", "صاروخ وقواطع", "power-tools"),
    ("sanders-polishers", "Sanders & Polishers", "صنفرة وتلميع", "power-tools"),
    ("demolition", "Rotary Hammers & Demolition", "هيلتي وهدم", "power-tools"),
    ("welding-tools", "Welding & Soldering Equipment", "معدات لحام", "power-tools"),
    ("power-tools-other", "Other Power Tools", "أدوات كهربائية أخرى", "power-tools"),
    # Measurement
    ("tape-rules", "Tape Measures & Rules", "شرائط قياس ومساطر", "measurement"),
    ("levels-squares", "Levels & Squares", "ميزان مياه وزوايا", "measurement"),
    ("precision-measure", "Calipers & Micrometers", "قدمة وميكرومتر", "measurement"),
    ("test-instruments", "Test & Detection Instruments", "أجهزة قياس وكشف", "measurement"),
    ("measurement-other", "Other Measurement Tools", "أدوات قياس أخرى", "measurement"),
    # Accessories & consumables
    ("drill-bits", "Drill Bits & Holesaws", "بنط ومناشير أسطوانية", "tool-consumables"),
    ("blades-discs", "Blades & Cutting Discs", "شفرات وأقراص قطع", "tool-consumables"),
    ("abrasives", "Abrasives", "مواد كاشطة", "tool-consumables"),
    ("tool-storage", "Tool Storage & Workshop", "تخزين الأدوات والورشة", "tool-consumables"),
    ("work-lights", "Work Lights & Torches", "كشافات ومصابيح عمل", "tool-consumables"),
    ("consumables-other", "Other Accessories", "ملحقات أخرى", "tool-consumables"),
    # Pneumatic
    ("air-tools", "Air Tools", "أدوات هوائية", "pneumatic"),
    ("compressors", "Compressors", "كمبروسورات", "pneumatic"),
    ("pneumatic-accessories", "Air Fittings & Hoses", "وصلات وخراطيم هواء", "pneumatic"),
]

TOOLS = register_profile(
    DomainProfile(
        slug="tools",
        name_en="Tools & Equipment",
        name_ar="أدوات ومعدات",
        taxonomy=TAXONOMY,
        # Intentionally empty: sources for this vertical publish their own
        # categories, which are mapped through a crosswalk. Keyword inference over
        # industrial goods actively mis-files — "socket" matches socket wrenches
        # into an electronics connectors leaf — so there is no fallback guessing.
        category_rules=[],
        identifier_rules=(model_code,),
        shop_stated_identifiers=True,
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
