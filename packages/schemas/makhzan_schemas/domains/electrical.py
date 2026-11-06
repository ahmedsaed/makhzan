"""Electrical installation and industrial control gear.

Its own domain, deliberately not folded into `electronics`. The overlap is
superficial: both involve current, but a panel builder sourcing a contactor and
a hobbyist sourcing an op-amp are different trades with different vocabularies,
suppliers and price points. Putting a 205-product circuit-breaker catalogue
inside a taxonomy built around resistors and dev boards would serve neither.

The catalogue is dominated by switchgear (breakers, contactors, overload relays)
and control devices (push buttons, pilot lamps, PLCs), which is what an
industrial panel is made of.

No identifier extraction. Manufacturers do use catalogue references here
(Schneider LC1D09, Siemens 3RT), and they are genuine cross-supplier identifiers,
but only one supplier stocks this domain today — an extractor could only produce
false merges. Revisit with a second electrical source.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    # Groups
    ("protection", "Protection & Switchgear", "الحماية ولوحات التوزيع", None),
    ("motor-control", "Motor Control", "التحكّم في المحركات", None),
    ("switching", "Switches", "المفاتيح", None),
    ("control-signalling", "Control & Signalling", "التحكّم والإشارة", None),
    ("relays-timers", "Relays & Timers", "الريليهات والمؤقتات", None),
    ("automation", "Automation & Control", "الأتمتة والتحكّم", None),
    ("industrial-sensors", "Industrial Sensors", "الحسّاسات الصناعية", None),
    ("wiring-distribution", "Wiring & Distribution", "التوصيل والتوزيع", None),
    ("lighting", "Lighting", "الإضاءة", None),
    ("power-quality", "Power Supply & Quality", "مصادر وجودة الطاقة", None),
    # Protection
    ("circuit-breakers", "Circuit Breakers", "قواطع كهربائية", "protection"),
    ("rcd-elcb", "Earth Leakage Protection", "قواطع التسريب الأرضي", "protection"),
    ("overload-relays", "Overload Relays", "ريليه الحمل الزائد", "protection"),
    ("disconnectors", "Disconnectors & Isolators", "مفاتيح الفصل", "protection"),
    # Motor control
    ("contactors", "Contactors", "الكونتاكتورات", "motor-control"),
    ("motor-starters", "Motor Starters", "بادئات التشغيل", "motor-control"),
    ("vfd-soft-start", "VFDs & Soft Starters", "الإنفرتر والبادئ اللين", "motor-control"),
    # Switching
    ("general-switches", "Switches", "مفاتيح", "switching"),
    ("limit-switches", "Limit Switches", "مفاتيح الحد", "switching"),
    ("process-switches", "Pressure, Float & Flow Switches", "مفاتيح الضغط والسوائل", "switching"),
    # Control & signalling
    ("push-buttons", "Push Buttons", "أزرار الضغط", "control-signalling"),
    ("selector-switches", "Selector Switches", "مفاتيح الاختيار", "control-signalling"),
    ("pilot-lamps", "Pilot Lamps & Indicators", "لمبات البيان", "control-signalling"),
    ("control-stations", "Control Stations", "صناديق التحكّم", "control-signalling"),
    # Relays & timers
    ("relays", "Relays", "الريليهات", "relays-timers"),
    ("timers", "Timers", "المؤقتات", "relays-timers"),
    # Automation
    ("plc", "PLCs", "متحكّمات منطقية", "automation"),
    ("controllers", "Process Controllers", "متحكّمات العمليات", "automation"),
    ("signal-conditioning", "Signal Conditioning", "تكييف الإشارة", "automation"),
    # Industrial sensors
    ("inductive-sensors", "Inductive & Proximity Sensors", "حسّاسات الاقتراب", "industrial-sensors"),
    ("photoelectric-sensors", "Photoelectric Sensors", "حسّاسات ضوئية", "industrial-sensors"),
    ("capacitive-sensors", "Capacitive Sensors", "حسّاسات سعوية", "industrial-sensors"),
    ("motion-sensors", "Motion Sensors", "حسّاسات الحركة", "industrial-sensors"),
    (
        "process-sensors",
        "Pressure & Process Sensors",
        "حسّاسات الضغط والعمليات",
        "industrial-sensors",
    ),
    ("sensor-accessories", "Sensor Accessories", "ملحقات الحسّاسات", "industrial-sensors"),
    # Wiring & distribution
    ("sockets-plugs", "Sockets & Plugs", "مقابس وقوابس", "wiring-distribution"),
    ("terminal-blocks", "Terminal Blocks", "قواعد التوصيل", "wiring-distribution"),
    ("junctions", "Junctions & Connectors", "وصلات كهربائية", "wiring-distribution"),
    ("enclosures", "Panels & Enclosures", "اللوحات والصناديق", "wiring-distribution"),
    ("cable-management", "Cable Management", "تنظيم الكابلات", "wiring-distribution"),
    # Lighting
    ("lamps", "Lamps & Bulbs", "لمبات", "lighting"),
    ("floodlights", "Floodlights", "كشافات", "lighting"),
    ("emergency-lighting", "Emergency Lighting", "إضاءة الطوارئ", "lighting"),
    # Power supply & quality
    ("ups", "UPS", "مصادر طاقة غير منقطعة", "power-quality"),
    ("power-supplies", "Power Supplies", "مصادر التغذية", "power-quality"),
    ("stabilizers", "Stabilizers & PF Correction", "منظّمات الجهد وتحسين المعامل", "power-quality"),
    ("energy-meters", "Energy Meters", "عدادات الطاقة", "power-quality"),
]

ELECTRICAL = register_profile(
    DomainProfile(
        slug="electrical",
        name_en="Electrical & Control",
        name_ar="الكهرباء والتحكّم",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Catalogue reference",
        identifier_label_ar="رقم الكتالوج",
    )
)
