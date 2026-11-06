"""The electronics vertical — makhzan's first domain.

Everything here was previously module-level constants in taxonomy.py and
grouping.py. It is unchanged; it just lives behind a profile now so other
verticals can supply their own without forking the pipeline.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile
from makhzan_schemas.part_number import extract_part_number

# --- Taxonomy tree: (slug, name_en, name_ar, parent_slug) ------------------- #
# Parents are browse groups; leaves are what the resolver assigns.
TAXONOMY: list[tuple[str, str, str, str | None]] = [
    # Groups
    ("components", "Components", "المكوّنات", None),
    ("boards-modules", "Boards & Modules", "اللوحات والوحدات", None),
    ("power", "Power", "الطاقة", None),
    ("electromechanical", "Motors & Actuators", "المحرّكات والمشغّلات", None),
    ("printing-cnc", "3D Printing & CNC", "الطباعة ثلاثية الأبعاد و CNC", None),
    ("tools", "Tools & Equipment", "الأدوات والمعدات", None),
    ("prototyping", "Prototyping", "النماذج الأولية", None),
    ("other", "Accessories & Other", "إكسسوارات وأخرى", None),
    # Components
    ("resistors", "Resistors", "المقاومات", "components"),
    ("potentiometers", "Potentiometers", "المقاومات المتغيّرة", "components"),
    ("capacitors", "Capacitors", "المكثّفات", "components"),
    ("inductors", "Inductors & Transformers", "الملفّات والمحوّلات", "components"),
    ("transistors", "Transistors & MOSFETs", "الترانزستورات", "components"),
    ("diodes", "Diodes", "الثنائيات", "components"),
    ("ics", "Integrated Circuits", "الدوائر المتكاملة", "components"),
    ("regulators", "Voltage Regulators", "منظّمات الجهد", "components"),
    ("leds", "LEDs & Optoelectronics", "الليدات والضوئيات", "components"),
    ("crystals", "Crystals & Oscillators", "البلّورات والمذبذبات", "components"),
    ("connectors", "Connectors & Sockets", "الموصّلات والمقابس", "components"),
    ("switches-relays", "Switches & Relays", "المفاتيح والريليهات", "components"),
    ("fuses", "Fuses & Protection", "المصهرات والحماية", "components"),
    ("audio", "Audio", "الصوت", "components"),
    # Boards & modules
    ("dev-boards", "Microcontrollers & Dev Boards", "المتحكّمات ولوحات التطوير", "boards-modules"),
    ("sensors", "Sensors", "الحسّاسات", "boards-modules"),
    ("wireless", "Communication & Wireless", "الاتصالات واللاسلكي", "boards-modules"),
    ("displays", "Displays", "الشاشات", "boards-modules"),
    ("modules", "Modules", "الوحدات", "boards-modules"),
    # Power
    ("power-supplies", "Power Supplies & Converters", "مصادر الطاقة والمحوّلات", "power"),
    ("batteries", "Batteries & Chargers", "البطاريات والشواحن", "power"),
    ("solar", "Solar", "الطاقة الشمسية", "power"),
    ("fans-cooling", "Fans & Cooling", "المراوح والتبريد", "power"),
    # Electromechanical
    ("motors", "Motors", "المحرّكات", "electromechanical"),
    ("servos", "Servos & Actuators", "السيرفو والمشغّلات", "electromechanical"),
    # Printing / CNC
    ("printers-3d", "3D Printers", "الطابعات ثلاثية الأبعاد", "printing-cnc"),
    ("filament", "Filament & Resin", "الخامات والراتنج", "printing-cnc"),
    ("printer-parts", "Printer & CNC Parts", "قطع الطابعات و CNC", "printing-cnc"),
    ("mechanical", "Mechanical Parts", "الأجزاء الميكانيكية", "printing-cnc"),
    # Tools
    ("soldering", "Soldering", "أدوات اللحام", "tools"),
    ("hand-tools", "Hand & Repair Tools", "أدوات اليد والإصلاح", "tools"),
    ("measurement", "Measurement & Test", "القياس والاختبار", "tools"),
    # Prototyping
    ("prototyping-supplies", "Breadboards & Wires", "لوحات التجارب والأسلاك", "prototyping"),
    # Other
    ("accessories", "Accessories", "إكسسوارات", "other"),
]

# --- Resolver rules: (leaf_slug, [keywords]) — ORDER = priority, specific first #
# Keywords match at a left word boundary (so "led" doesn't fire inside
# "assembled") against normalized (decoded, lowercased) text. Trailing text is
# free, so "resistor" matches "resistors" — unless the keyword ends in "\b",
# which makes it a whole word: "pla\b" is PLA, not "plate" or "plastic".
#
# A leaf may appear twice when part of its vocabulary must outrank another leaf
# and part must not (see 3D printers below).
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("resistors", ["resistor"]),
    ("potentiometers", ["potentiometer", "trimmer", "rheostat"]),
    ("capacitors", ["capacitor"]),
    ("inductors", ["inductor", "transformer", "choke"]),
    ("transistors", ["transistor", "mosfet", "bjt", "igbt"]),
    ("regulators", ["regulator", "ldo"]),
    ("crystals", ["crystal", "oscillator", "resonator"]),
    (
        "displays",
        ["lcd", "tft", "oled", "display", "screen", "lcm", "e-paper", "epaper", "nextion"],
    ),
    ("leds", ["led", "optocoupler", "photodiode", "seven segment", "7-segment"]),
    ("diodes", ["diode", "rectifier", "zener"]),
    ("ics", ["integrated circuit", "74 series", "74hc", "op-amp", "op amp", "opamp", "logic gate"]),
    ("audio", ["microphone", "speaker", "buzzer", "electret", "piezo", "mems mic"]),
    ("connectors", ["connector", "socket", "header", "terminal", "jst", "dupont", "screw block"]),
    (
        "switches-relays",
        ["switch", "relay", "push button", "tactile", "rocker", "keypad", "keyboard"],
    ),
    ("fuses", ["fuse", "varistor", "tvs"]),
    (
        "dev-boards",
        [
            "arduino",
            "esp32",
            "esp8266",
            "esp-",
            "raspberry",
            "microcontroller",
            "development board",
            "dev board",
            "devkit",
            "stm32",
            "nodemcu",
            "microbit",
            "pi pico",
            "rp2040",
            "fpga",
        ],
    ),
    (
        "wireless",
        [
            "wireless",
            "bluetooth",
            "wifi",
            "wi-fi",
            "lora",
            "gsm",
            "gps",
            "gprs",
            "nrf",
            "zigbee",
            "rf module",
            "433mhz",
            "antenna",
            "4g",
            "3g",
            "sim800",
        ],
    ),
    ("sensors", ["sensor", "encoder"]),
    ("solar", ["solar"]),
    (
        "power-supplies",
        [
            "power supply",
            "converter",
            "buck",
            "boost",
            "smps",
            "adapter",
            "dc-dc",
            "dc dc",
            "psu",
            "step down",
            "step up",
            "inverter",
        ],
    ),
    (
        "batteries",
        ["battery", "batteries", "charger", "18650", "lipo", "li-ion", "li ion", "cell holder"],
    ),
    ("fans-cooling", ["fan", "cooling", "heatsink", "heat sink", "thermal"]),
    ("motors", ["motor"]),
    ("servos", ["servo", "actuator", "stepper", "solenoid"]),
    # Only the phrases that cannot describe anything but a printer go ahead of
    # filament, which has to beat "resin" in "Resin 3D Printer".
    (
        "printers-3d",
        ["resin printer", "resin 3d printer", "fdm printer", "sla printer", "printer combo"],
    ),
    # Ahead of plain "3d printer": reels are sold "for 3D Printer", and the tag
    # "3D Printer Filament" filed 61 listings as printers. The short names are
    # whole words — as prefixes, "pla" filed plates and plastic gears as filament.
    ("filament", ["filament", "resin", r"pla\b", r"abs\b", "petg", "tpu"]),
    ("soldering", ["solder", "flux", "desolder"]),
    (
        "hand-tools",
        [
            "hand tool",
            "repair tool",
            "screwdriver",
            "plier",
            "tweezer",
            "cutter",
            "wrench",
            "knife",
            "heat gun",
            "glue gun",
        ],
    ),
    (
        "printer-parts",
        [
            "3d printer part",
            "printer part",
            "for 3d printer",
            "cnc",
            "nozzle",
            "hotend",
            "extruder",
            "heat bed",
        ],
    ),
    # Last of the printing leaves: "Extrusion Nozzle for 3D Printer" and "PLA
    # Filament Roll for 3D Printer" name a printer only as what they fit.
    ("printers-3d", ["3d printer"]),
    (
        "mechanical",
        [
            "screw",
            "nut",
            "spacer",
            "standoff",
            "bolt",
            "bearing",
            "coupler",
            "coupling",
            "pulley",
            "timing belt",
            "gt2",
            "lead screw",
            "threaded rod",
            "bracket",
            "washer",
            "aluminum profile",
            "v-slot",
        ],
    ),
    (
        "measurement",
        [
            "multimeter",
            "oscilloscope",
            "uni-t",
            "unit-t",
            "measurement",
            "test equipment",
            "power meter",
            "lcr",
            "clamp meter",
            "tester",
            "logic analyzer",
        ],
    ),
    (
        "prototyping-supplies",
        [
            "breadboard",
            "jumper",
            "dupont wire",
            "perfboard",
            "protoboard",
            "pcb",
            "prototyping",
            "hook up wire",
        ],
    ),
    ("modules", ["module"]),
    ("accessories", ["accessor", "mobile", "computer"]),
]

_GENERIC = {
    "components",
    "component",
    "devices",
    "electronics",
    "products",
    "all products",
    "new",
    # Names two leaves at once, so it cannot say which a listing is. One shop's
    # tag of this name holds filament reels, printers, nozzles and bearings
    # alike; read as a category it filed all 94 under one leaf. The title can
    # tell them apart.
    "3d printer filament",
}

# Generic descriptors that don't distinguish products — dropped from title signatures.
_NOISE = {
    "board",
    "module",
    "kit",
    "dev",
    "devkit",
    "development",
    "new",
    "original",
    "genuine",
    "pcs",
    "pc",
    "set",
    "pack",
    "with",
    "for",
    "the",
    "and",
    "mini",
    "pro",
    "plus",
    "max",
    "lite",
    "wifi",
    "bluetooth",
    "ble",
    "wireless",
    "usb",
    "type",
    "microcontroller",
    "chip",
    "ic",
    "breakout",
    "shield",
    "node",
    "nodemcu",
    "based",
    "compatible",
    "high",
    "quality",
    "egypt",
    "micro",
}


# A bare chip and the module built around it share a part number and, once
# "module", "board" and "ic" are stripped as noise, most of their words: a TP4056
# SOP-8 sat inside a six-shop charger-module product, and DS1302/DS1307 RTC ICs at
# 15 EGP inside their 50 EGP modules. Module wins when a title says both ("module
# with TP4056 IC" is a module); a package name alone ("4-DIP", "SOP-8") says chip.
#
# Accessories come first and are strict (see `accessory_forms`): "Ultrasonic Sensor
# Mounting Bracket For HC-SR04" shares two of its five words with "Ultrasonic
# Sensor HC-SR04", which clears the similarity threshold, and costs 15 EGP against
# 40 — inside the price band. Nothing else tells a bracket from the sensor.
#
# Two of those words also describe the part itself. "PCB Mount", "Panel Mount",
# "Surface Mount" and "DIN Rail Mount" say how a connector, switch or relay is
# fitted, not that the listing is a mount for it, so they vetoed real merges; a
# "servo mount" or "motor mount" is still an accessory. Likewise "ESP-01 with
# adapter" is the module, sold with its adapter.
_MOUNTING_STYLES = ("pcb", "panel", "surface", "rail", "chassis", "screw", "hole")
_NOT_A_MOUNT = "".join(f"(?<!{style}{sep})" for style in _MOUNTING_STYLES for sep in " -")
_FORM_MARKERS = (
    (
        "accessory",
        r"\b(?:brackets?|holders?|mounting|cases?|covers?|enclosure|housing|stand"
        r"|expansion|heat\s?sinks?)\b"
        rf"|{_NOT_A_MOUNT}\bmounts?\b"
        r"|(?<!with )(?<!with an )\badapters?\b",
    ),
    ("module", r"\b(?:modules?|boards?|shields?|kits?|breakout|devkit|development)\b"),
    (
        "chip",
        r"\b(?:ics?|chips?|smd|p?dip|soic|sop|[st]?ssop|msop|[lt]?qfp|qfn|sot-?\d+|to-?\d+)\b",
    ),
)


ELECTRONICS = register_profile(
    DomainProfile(
        slug="electronics",
        name_en="Electronics",
        name_ar="إلكترونيات",
        taxonomy=TAXONOMY,
        category_rules=CATEGORY_RULES,
        generic_categories=frozenset(_GENERIC),
        extract_identifier=extract_part_number,
        noise_tokens=frozenset(_NOISE),
        cluster_threshold=0.34,
        form_markers=_FORM_MARKERS,
        accessory_forms=frozenset({"accessory"}),
        # Electronics search is part-number driven, so the identifier ranks first.
        search_attributes=("part_number", "title_en", "title_ar", "brand"),
        identifier_label_en="Part number",
        identifier_label_ar="رقم القطعة",
    )
)
