"""
ShopMate AI — Spec Facts (Phase 4)

Turns a product's messy spec list (as Flipkart writes it) into a small
set of CHECKED, typed facts, e.g. "RAM": "8 GB"  ->  ram_gb = 8.0.

Three rules keep this honest:
  1. A fact is created only when the listing states it clearly.
  2. If the listing says two different things (e.g. "Noise Cancellation: No"
     but "Active Noise Cancellation: Yes"), NO fact is created and the key
     is reported as a conflict. We never pick a side.
  3. If the listing is silent, the fact is simply absent. Absent means
     "unknown", never "no".

extract_spec_facts(category, flat_specs) -> (facts, conflicts)
"""

import re

from app.schemas.product import SpecFact

# Which facts form the comparison table for each category: (fact key, column label).
COMPARISON_SPECS: dict[str, list[tuple[str, str]]] = {
    "earphones": [
        ("connectivity", "Connectivity"),
        ("noise_cancellation", "Noise cancellation"),
        ("battery_hours", "Battery life"),
        ("water_resistant", "Water resistant"),
    ],
    "smartphones": [
        ("ram_gb", "RAM"),
        ("storage_gb", "Storage"),
        ("battery_mah", "Battery"),
        ("rear_camera_mp", "Rear camera"),
        ("network_5g", "5G"),
        ("display_inches", "Display"),
    ],
    "laptops": [
        ("processor", "Processor"),
        ("ram_gb", "RAM"),
        ("storage_gb", "Storage"),
        ("screen_inches", "Screen"),
        ("weight_kg", "Weight"),
    ],
    "running_shoes": [
        ("outer_material", "Outer material"),
        ("sole_material", "Sole"),
        ("closure", "Closure"),
        ("ideal_for", "Ideal for"),
        ("weight_g", "Weight (per shoe)"),
    ],
    "smartwatches": [
        ("battery_days", "Battery life"),
        ("display_inches", "Display"),
        ("calling", "Calling"),
        ("gps", "GPS"),
        ("water_resistant", "Water resistant"),
    ],
}


# ---------------------------------------------------------------- helpers


def _blank(value) -> bool:
    return value is None or str(value).strip().lower() in {"", "na", "n/a", "nan", "none", "-", "null", "not applicable"}


class _Specs:
    """Case-insensitive view over the flat spec dict."""

    def __init__(self, flat: dict[str, str]):
        self._index = {k.strip().lower(): str(v).strip() for k, v in flat.items() if not _blank(v)}

    def get(self, *keys: str) -> str | None:
        for key in keys:
            value = self._index.get(key.lower())
            if value is not None:
                return value
        return None


def parse_yes_no(value: str | None) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"yes", "y", "true", "available", "present"}:
        return True
    if text in {"no", "n", "false", "not available"}:
        return False
    return None


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def parse_hours(text: str | None) -> float | None:
    """'60 hr', '40 Hours', 'Up to 8 hours', '30-40 hrs' (a range gives its lower end). A bare number is NOT hours."""
    if not text:
        return None
    unit = r"(?:hours?|hrs?|h)\b"
    ranged = re.search(rf"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*{unit}", text, re.I)
    if ranged:
        return float(ranged.group(1))
    single = re.search(rf"(\d+(?:\.\d+)?)\s*\+?\s*{unit}", text, re.I)
    return float(single.group(1)) if single else None


def parse_days(text: str | None) -> float | None:
    """'5 Days', 'Upto 7 days'. Hours are converted to days."""
    if not text:
        return None
    days = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(?:\d+(?:\.\d+)?)?\s*days?\b", text, re.I)
    if days:
        return float(days.group(1))
    hours = parse_hours(text)
    return round(hours / 24, 1) if hours is not None else None


def parse_gb(text: str | None) -> float | None:
    """'8 GB' -> 8, '1 TB' -> 1024, '512 MB' -> 0.5"""
    if not text:
        return None
    match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(tb|gb|mb)\b", text, re.I)
    if not match:
        return None
    value, unit = _num(match.group(1)), match.group(2).lower()
    return value * 1024 if unit == "tb" else value / 1024 if unit == "mb" else value


def parse_mah(text: str | None) -> float | None:
    match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*mah", text or "", re.I)
    return _num(match.group(1)) if match else None


def parse_mp(text: str | None) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mp", text or "", re.I)
    return float(match.group(1)) if match else None


def parse_inches(text: str | None) -> float | None:
    """'16.92 cm (6.66 inch)' -> 6.66, '15.6 Inch' -> 15.6, '39.62 cm' -> 15.6"""
    if not text:
        return None
    bracket = re.search(r"\((\d+(?:\.\d+)?)\s*(?:inch(?:es)?|\")", text, re.I)
    if bracket:
        return float(bracket.group(1))
    plain = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch(?:es)?|\")", text, re.I)
    if plain:
        return float(plain.group(1))
    cm = re.search(r"(\d+(?:\.\d+)?)\s*cm\b", text, re.I)
    return round(float(cm.group(1)) / 2.54, 1) if cm else None


def parse_watch_inches(text: str | None) -> float | None:
    """
    Watch display sizes are listed as inches ('1.83 inch') but some listings write the same
    kind of number in mm ('1.3 mm'). A 1.3 mm screen is impossible, so a small number labelled
    mm is read as inches. A big mm number (46.4 mm) is the case size, not the screen, so it is
    left unknown rather than converted.
    """
    if not text:
        return None
    inches = parse_inches(text)
    if inches is not None:
        return inches
    mm = re.search(r"(\d+(?:\.\d+)?)\s*mm\b", text, re.I)
    if mm and float(mm.group(1)) < 5:
        return float(mm.group(1))
    return None


def parse_kg(text: str | None) -> float | None:
    kg = re.search(r"(\d+(?:\.\d+)?)\s*kgs?\b", text or "", re.I)
    if kg:
        return float(kg.group(1))
    grams = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)\b", text or "", re.I)
    return round(float(grams.group(1)) / 1000, 3) if grams else None


def parse_grams(text: str | None) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)\b", text or "", re.I)
    return float(match.group(1)) if match else None


def parse_version(text: str | None) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else None


def _fmt(value: float) -> str:
    return f"{value:g}"


def _gb_display(value: float) -> str:
    return f"{_fmt(value / 1024)} TB" if value >= 1024 else f"{_fmt(value)} GB"


def _merge_bool(*values: bool | None) -> tuple[bool | None, bool]:
    """(value, conflict). Disagreeing sources give no value and a conflict."""
    known = [v for v in values if v is not None]
    if not known:
        return None, False
    if len(set(known)) > 1:
        return None, True
    return known[0], False


class _Builder:
    def __init__(self):
        self.facts: dict[str, SpecFact] = {}
        self.conflicts: list[str] = []

    def put(self, key: str, value, display: str):
        self.facts[key] = SpecFact(value=value, display=display)

    def number(self, key: str, value: float | None, display_fn):
        if value is not None:
            self.put(key, float(value), display_fn(value))

    def boolean(self, key: str, *values: bool | None):
        value, conflict = _merge_bool(*values)
        if conflict:
            self.conflicts.append(key)
        elif value is not None:
            self.put(key, value, "Yes" if value else "No")

    def text(self, key: str, raw: str | None, display: str | None = None):
        if raw:
            self.put(key, raw.strip().lower(), display or raw.strip())


# ---------------------------------------------------------------- per category


def _earphones(s: _Specs) -> _Builder:
    b = _Builder()
    connectivity = s.get("Connectivity", "Wireless Type")
    if connectivity:
        low = connectivity.lower()
        if "bluetooth" in low or "wireless" in low:
            b.put("connectivity", "wireless", "Wireless (Bluetooth)")
        elif "wired" in low:
            b.put("connectivity", "wired", "Wired")

    true_wireless = parse_yes_no(s.get("True Wireless"))
    headphone_type = (s.get("Headphone Type") or "").lower()
    if headphone_type == "true wireless" and true_wireless is False:
        b.conflicts.append("true_wireless")
    elif true_wireless is not None:
        b.boolean("true_wireless", true_wireless)
    elif headphone_type == "true wireless":
        b.boolean("true_wireless", True)

    b.boolean("noise_cancellation", parse_yes_no(s.get("Noise Cancellation")), parse_yes_no(s.get("Active Noise Cancellation")))

    play, life = parse_hours(s.get("Play Time")), parse_hours(s.get("Battery Life"))
    if play is not None and life is not None and abs(play - life) > 1:
        b.conflicts.append("battery_hours")
    else:
        b.number("battery_hours", play if play is not None else life, lambda v: f"{_fmt(v)} hours")

    b.boolean("water_resistant", parse_yes_no(s.get("Water Resistant")))
    b.boolean("sweat_proof", parse_yes_no(s.get("Sweat Proof")))
    b.boolean("fast_charging", parse_yes_no(s.get("Fast Charging")))
    b.boolean("microphone", parse_yes_no(s.get("With Microphone")))
    version = parse_version(s.get("Bluetooth Version"))
    if version is not None and 3 <= version <= 7:
        b.number("bluetooth_version", version, lambda v: f"Bluetooth {_fmt(v)}")
    return b


def _smartphones(s: _Specs) -> _Builder:
    b = _Builder()
    b.number("ram_gb", parse_gb(s.get("RAM")), _gb_display)
    b.number("storage_gb", parse_gb(s.get("Internal Storage")), _gb_display)
    b.number("battery_mah", parse_mah(s.get("Battery Capacity")), lambda v: f"{_fmt(v)} mAh")
    b.number("display_inches", parse_inches(s.get("Display Size")), lambda v: f"{_fmt(v)} inches")

    networks = " ".join(filter(None, [s.get("Network Type"), s.get("Supported Networks")]))
    if networks:
        has_5g = bool(re.search(r"\b5g\b", networks, re.I))
        b.put("network_5g", has_5g, "Yes" if has_5g else "No")

    os_text = s.get("Operating System")
    if os_text:
        cleaned = re.sub(r"\b(\w+)\s+\1\b", r"\1", os_text, flags=re.I)
        b.put("os", cleaned.lower(), cleaned)

    chip_type, chip_brand = s.get("Processor Type"), s.get("Processor Brand")
    if chip_type or chip_brand:
        display = chip_type if chip_type and chip_brand and chip_brand.lower() in chip_type.lower() else " ".join(filter(None, [chip_brand, chip_type]))
        b.put("processor", display.lower(), display)

    b.number("rear_camera_mp", parse_mp(s.get("Primary Camera")), lambda v: f"{_fmt(v)} MP")
    b.number("front_camera_mp", parse_mp(s.get("Secondary Camera")), lambda v: f"{_fmt(v)} MP")

    refresh = re.search(r"refresh rate\s*:?\s*(\d{2,3})\s*hz", " ".join(filter(None, [s.get("Other Display Features"), s.get("Display Features")])), re.I)
    if refresh:
        b.number("refresh_rate_hz", float(refresh.group(1)), lambda v: f"{_fmt(v)} Hz")

    b.boolean("fast_charging", parse_yes_no(s.get("Quick Charging")))
    b.boolean("nfc", parse_yes_no(s.get("NFC")))

    display_text = " ".join(filter(None, [s.get("Display Type"), s.get("Resolution Type"), s.get("Other Display Features")]))
    if re.search(r"\bamoled\b|\boled\b", display_text, re.I):
        b.put("amoled", True, "Yes")
    elif re.search(r"\blcd\b|\bips\b|\btft\b", s.get("Display Type") or "", re.I):
        b.put("amoled", False, "No")
    return b


def _laptops(s: _Specs) -> _Builder:
    b = _Builder()
    b.number("ram_gb", parse_gb(s.get("RAM")), _gb_display)

    storage_type = s.get("Storage Type")
    if storage_type:
        is_ssd = storage_type.strip().lower() == "ssd"
        b.put("ssd", is_ssd, "Yes" if is_ssd else "No")
        b.text("storage_type", storage_type)
    capacity = parse_gb(s.get("SSD Capacity")) or parse_gb(s.get("EMMC Storage Capacity")) or parse_gb(s.get("UFS Storage Capacity"))
    b.number("storage_gb", capacity, _gb_display)

    parts = [s.get("Processor Brand"), s.get("Processor Name"), s.get("Processor Variant")]
    if any(parts):
        display = " ".join(p for p in parts if p)
        b.put("processor", display.lower(), display)

    b.number("screen_inches", parse_inches(s.get("Screen Size")), lambda v: f"{_fmt(v)} inches")
    b.number("weight_kg", parse_kg(s.get("Weight")), lambda v: f"{_fmt(v)} kg")
    b.text("os", s.get("Operating System"))
    b.boolean("touchscreen", parse_yes_no(s.get("Touchscreen")))
    b.boolean("backlit_keyboard", parse_yes_no(s.get("Backlit Keyboard")))
    b.text("laptop_type", s.get("Type"))
    b.number("battery_hours", parse_hours(s.get("Battery Backup")), lambda v: f"{_fmt(v)} hours")

    gpu = s.get("Graphic Processor") or ""
    dedicated_memory = parse_gb(s.get("Dedicated Graphic Memory Capacity"))
    if dedicated_memory or re.search(r"nvidia|geforce|rtx|gtx", gpu, re.I):
        b.put("dedicated_graphics", True, "Yes")
    elif "integrated" in gpu.lower():
        b.put("dedicated_graphics", False, "No (integrated)")
    return b


def _running_shoes(s: _Specs) -> _Builder:
    b = _Builder()
    b.text("outer_material", s.get("Outer material"))
    b.text("sole_material", s.get("Sole material"))
    b.text("closure", s.get("Closure"))
    b.text("ideal_for", s.get("Ideal for", "Ideal For"))
    grams = parse_grams(s.get("Weight"))
    if grams is not None and 20 <= grams <= 2000:  # listings contain impossible weights like '0.65 g'
        b.number("weight_g", grams, lambda v: f"{_fmt(v)} g")
    return b


def _smartwatches(s: _Specs) -> _Builder:
    b = _Builder()
    b.number("battery_days", parse_days(s.get("Battery Life")) or parse_days(s.get("Battery Run Time")), lambda v: f"{_fmt(v)} days")
    b.number("display_inches", parse_watch_inches(s.get("Display Size")), lambda v: f"{_fmt(v)} inches")
    b.boolean("calling", parse_yes_no(s.get("Call Function")), parse_yes_no(s.get("Voice Caling")))
    b.boolean("sim", parse_yes_no(s.get("Sim Slot Present")))
    b.boolean("water_resistant", parse_yes_no(s.get("Water Resistant")))
    b.boolean("gps", parse_yes_no(s.get("GPS")))

    sensors = s.get("Sensor") or ""
    heart = parse_yes_no(s.get("Heart Rate Monitor"))
    if heart is None and re.search(r"heart", sensors, re.I):
        heart = True
    b.boolean("heart_rate", heart)
    b.text("sensors", sensors or None)
    b.text("display_type", s.get("Display Type"))
    b.text("compatible_os", s.get("Compatible OS"))
    b.text("dial_shape", s.get("Dial Shape"))
    b.text("strap_material", s.get("Strap Material"))
    return b


_EXTRACTORS = {
    "earphones": _earphones,
    "smartphones": _smartphones,
    "laptops": _laptops,
    "running_shoes": _running_shoes,
    "smartwatches": _smartwatches,
}


def extract_spec_facts(category: str, flat_specs: dict[str, str]) -> tuple[dict[str, SpecFact], list[str]]:
    extractor = _EXTRACTORS.get(category)
    if extractor is None:
        return {}, []
    built = extractor(_Specs(flat_specs))
    return built.facts, built.conflicts