"""Conservative, local attribute extraction. Missing values never establish equivalence."""

import re
from dataclasses import asdict, dataclass, field

COMPONENTS = ("mask", "gown", "glove", "catheter", "stylet", "gauze", "needle", "syringe", "drape", "sponge", "forceps", "scalpel", "swab", "towel")
NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
UNIT = r'(?:mm\b|cm\b|inches\b|inch\b|in\b|["″])'
DIMENSION = re.compile(rf"({NUMBER})\s*({UNIT})?\s*x\s*({NUMBER})\s*({UNIT})", re.IGNORECASE)


@dataclass
class Attributes:
    component_type: str | None = None
    dimensions_mm: list[float] = field(default_factory=list)
    gauge: float | None = None
    concentration_pct: float | None = None
    pack_quantity: int | None = None

    def to_dict(self):
        return asdict(self)


def extract_attributes(text: str) -> Attributes:
    text = text.lower().replace("×", "x")
    out = Attributes()
    nouns = [(m.start(), noun) for noun in COMPONENTS if (m := re.search(rf"\b{noun}(?:s)?\b", text))]
    if nouns:
        out.component_type = min(nouns)[1]
    # Explicit units only; a trailing unit covers both dimensions (4 x 4 in).
    dimension = DIMENSION.search(text)
    def mm(value, unit):
        return round(float(value) * (10 if unit == "cm" else 1 if unit == "mm" else 25.4), 4)
    if dimension:
        out.dimensions_mm = sorted([mm(dimension[1], dimension[2] or dimension[4]), mm(dimension[3], dimension[4])])
    else:
        lengths = re.findall(rf"({NUMBER})\s*({UNIT})(?![a-z])", text)
        out.dimensions_mm = sorted(mm(v, u) for v, u in lengths[:3])
    gauge_unit = r"(?:gauge|ga\b|g\b)" if out.component_type in ("needle", "catheter") else r"(?:gauge|ga\b)"
    gauge = re.search(rf"\b({NUMBER})\s*{gauge_unit}", text) or re.search(rf"\bgauge\s*({NUMBER})", text)
    if gauge:
        out.gauge = float(gauge[1])
    concentration = re.search(rf"({NUMBER})\s*%", text)
    if concentration:
        out.concentration_pct = float(concentration[1])
    pack = re.search(r"\bpack\s+of\s+(\d+)\b", text) or re.search(r"\b(\d+)\s*(?:per\b|/\s*(?:pack|pouch)\b|pack\b)", text)
    if pack:
        out.pack_quantity = int(pack[1])
    return out


def attribute_conflicts(a: Attributes, b: Attributes) -> list[str]:
    conflicts = []
    for name in ("component_type", "gauge", "concentration_pct", "pack_quantity"):
        av, bv = getattr(a, name), getattr(b, name)
        if av is not None and bv is not None and av != bv:
            conflicts.append(f"{name}: {av} vs {bv}")
    if a.dimensions_mm and b.dimensions_mm and (
        len(a.dimensions_mm) != len(b.dimensions_mm)
        or any(abs(x - y) > max(0.01, max(x, y) * 0.03) for x, y in zip(sorted(a.dimensions_mm), sorted(b.dimensions_mm)))
    ):
        conflicts.append(f"dimensions_mm: {a.dimensions_mm} vs {b.dimensions_mm}")
    return conflicts
