"""Manufacturer part-number (MPN) extraction from product titles.

Regex hybrid: a set of known component families (high precision) plus a guarded
generic pattern (recall). Deliberately conservative — when unsure it returns
None, because a wrong MPN would create a wrong dedup grouping later. Under-
extraction (a singleton product) is always safer than a false merge.

Operates on the UPPERCASED title. Returns a normalized MPN or None.
"""

from __future__ import annotations

import re

# Known component families — ordered isn't important; the leftmost match wins.
# Trailing charclass is alnum (no hyphens) except where a hyphen is intrinsic.
_KNOWN_SRC = [
    r"LM\d{2,4}[A-Z0-9]*",  # LM358, LM7805, LM317T
    r"(?:NE|SE)\d{3}[A-Z0-9]*",  # NE555
    r"TL\d{2,4}[A-Z0-9]*",  # TL072, TL431
    r"(?:UA|LA|KA)\d{3,4}[A-Z0-9]*",
    r"74[A-Z]{0,4}\d{2,4}[A-Z0-9]*",  # 7400, 74HC595, 74LS138
    r"CD4\d{3}[A-Z0-9]*",  # CD4017
    r"2N\d{3,4}[A-Z]?",  # 2N2222, 2N3904
    r"2S[ABCD]\d{3,4}[A-Z]?",  # 2SC1815
    r"BC\d{3}[A-Z]?",  # BC547
    r"BD\d{3}[A-Z]?",
    r"TIP\d{2,3}[A-Z]?",  # TIP122
    r"IRF[A-Z]?\d{3,4}[A-Z0-9]*",  # IRF540N, IRFZ44N
    r"1N\d{3,4}[A-Z]?",  # 1N4007, 1N4148
    r"(?:78|79)\d{2}[A-Z0-9]*",  # 7805, 7812, 7905
    r"AMS1117(?:-?\d(?:\.\d)?)?",  # AMS1117-3.3
    r"LD1117[A-Z0-9]*",
    r"ATMEGA\d+[A-Z0-9]*",
    r"ATTINY\d+[A-Z0-9]*",
    r"AT89[A-Z]\d+[A-Z0-9]*",
    r"STM32[A-Z]\d[A-Z0-9]*",  # STM32F103C8T6
    r"STM8[A-Z]\d+[A-Z0-9]*",
    r"ESP8266[A-Z0-9]*",
    r"ESP32(?:-[A-Z0-9]+)*",  # ESP32-WROOM-32
    r"ESP-\d{2}[A-Z]?",  # ESP-01
    r"PIC\d{2}[A-Z]\d+[A-Z0-9]*",  # PIC16F877A
    r"RP2040",
    r"NRF\d{4,5}[A-Z0-9]*",  # NRF24L01
    r"MAX\d{3,4}[A-Z0-9]*",  # MAX7219, MAX485
    r"ULN\d{3,4}[A-Z]?",  # ULN2003, ULN2803
    r"L293[A-Z]?",  # L293D
    r"L298[A-Z]?",  # L298N
    r"MCP\d{3,4}[A-Z0-9]*",
    r"PCF\d{3,4}[A-Z0-9]*",  # PCF8574
    r"DS\d{4}[A-Z0-9]*",  # DS1307, DS18B20
    r"DHT\d{2}",  # DHT11, DHT22
    r"BM[EP]\d{3}",  # BME280, BMP180
    r"MPU\d{4}",  # MPU6050
    r"ADXL\d{3}",  # ADXL345
    r"ADS\d{4}[A-Z0-9]*",  # ADS1115
    r"TP4056",
    r"HC-?SR\d{2,3}",  # HC-SR04, HC-SR501
    r"HX\d{3,4}",  # HX711
    r"A4988",
    r"DRV\d{3,4}[A-Z0-9]*",  # DRV8825
    r"XL\d{4}",  # XL6009
    r"MT\d{4}[A-Z0-9]*",  # MT3608
    r"IR2\d{3}[A-Z0-9]*",  # IR2104
    r"SIM\d{3,4}[A-Z0-9]*",  # SIM800L
    r"W5500",
    r"ENC28J60",
    r"SSD1306",
    r"PCA\d{4}[A-Z0-9]*",  # PCA9685
    r"TCA\d{4}[A-Z0-9]*",  # TCA9548A
]
_KNOWN = [re.compile(r"\b" + src) for src in _KNOWN_SRC]

# Generic: 1-5 leading letters, then >=2 digits, then alnum + optional hyphen groups.
# Leading letters exclude digit-first units (12V, 680UF) automatically.
_GENERIC = re.compile(r"\b[A-Z]{1,5}[0-9]{2,}[A-Z0-9]*(?:-[A-Z0-9]+)*")

# Tokens that look like part numbers but aren't: interfaces, packages, gauges,
# and — importantly — ratings/sizes (IP65, NEMA17) that would merge unrelated products.
_BLOCK = re.compile(
    r"^(RS232|RS485|RS422|I2C|USB2|USB3|DB9|DB25|RJ45|HDMI|VGA|MP3|"
    r"AWG\d+|TO\d+|SOT\d+|SOP\d+|SOIC\d*|DIP\d+|QFP\d+|TQFP\d+|DO\d+|SMD\d*|"
    r"TSSOP\d*|MSOP\d*|BGA\d*|LCD\d*|OLED\d*|"
    r"IP\d{2}|NEMA\d+|M\d+X\d+)$"  # IP rating, NEMA frame size, M3X10 screw
)


def _clean(token: str) -> str:
    return token.strip("-.").upper()


def extract_part_number(text: str | None) -> str | None:
    """Extract a normalized MPN from a product title, or None if none is confident.

    MPNs lead titles, so the leftmost candidate wins; a known family beats a
    generic token at the same position. This picks a board's own code over a
    chip it merely mentions (e.g. "T-A7608SA-H ESP32 GPS" -> A7608SA-H).
    """
    if not text:
        return None
    upper = text.upper()

    # (position, cleaned_token, priority) — priority 0 = known family, 1 = generic.
    candidates: list[tuple[int, str, int]] = []
    for pattern in _KNOWN:
        m = pattern.search(upper)
        if m:
            candidates.append((m.start(), _clean(m.group(0)), 0))
    for m in _GENERIC.finditer(upper):
        token = m.group(0)
        if _BLOCK.match(token) or not (3 <= len(token) <= 24):
            continue
        candidates.append((m.start(), _clean(token), 1))

    candidates = [c for c in candidates if 2 <= len(c[1]) <= 24]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[2]))
    return candidates[0][1]
