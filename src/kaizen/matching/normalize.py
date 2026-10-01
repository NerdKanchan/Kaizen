"""Deterministic text normalisation. Conservative on purpose: it removes noise, never meaning.

Every transformation is listed here so a reviewer can read what "normalised" means.
"""

import re
import unicodedata
from dataclasses import dataclass, field

NORMALIZER_VERSION = "3"

_TRADEMARK_CHARS = "™®©℠"  # ™ ® © ℠ — stripped before NFKC (NFKC would turn ™ into "TM")
# OCR writes the ™ sign as the letters TM, glued to the name (SherlockTM, 3CGTM) or as a separate word.
# Both are dropped like the symbol. A glued TM is removed only from words holding a lowercase letter or a
# digit, so an all-caps word such as ATM is left alone.
_TEXT_TRADEMARK_RE = re.compile(r"\b((?=[A-Za-z0-9]*[a-z0-9])[A-Za-z0-9]{2,}?)TM\b")
_DASHES = "–—‐‑‒"  # – — ‐ ‑ ‒
_UNITS = ("ML", "CM", "MM", "IN", "FT", "MG", "KG", "GA", "FR", "CC", "OZ", "G", "F", "L", "M")
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(_UNITS) + r")\b\.?")
_DIM_RE = re.compile(r"(\d)X(\d)")
_TRAILING_ZERO_RE = re.compile(r"(\d+)\.0+(?=[A-Z%]|\s|$)")
_PERCENT_RE = re.compile(r"(\d)\s+%")
_PUNCT_RE = re.compile(r"[^A-Z0-9.%\s]")
_STRAY_DOT_RE = re.compile(r"(?<!\d)\.|\.(?!\d)")
_NUMERIC_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)([A-Z]{1,2}|%)?$")

# Curated abbreviation expansions. Deliberately tiny; every entry must be unambiguous in this domain.
ABBREVIATIONS: dict[str, str] = {
    "ASSY": "ASSEMBLY",
    "PKG": "PACKAGE",
    # Observed OCR / ERP variants in the real BD delivery. These are wording
    # corrections, not semantic guesses, so they are safe before review.
    "MEASUARING": "MEASURING",
    "HCI": "HCL",
    "HCIL": "HCL",
}

_LENGTH_UNITS_INCHES = {"MM": 1 / 25.4, "CM": 1 / 2.54, "IN": 1.0, "FT": 12.0}

# Words ending in S that are not plurals.
_SINGULAR_EXCEPTIONS = {"LENS", "PLUS", "STATUS", "VERSUS", "GAS", "BUS", "BOLUS", "ATLAS", "CANVAS", "IRIS", "PELVIS"}


@dataclass(frozen=True)
class NormalizedText:
    raw: str
    normalized: str
    tokens: list[str] = field(default_factory=list)
    sorted_key: str = ""
    numeric_tokens: list[str] = field(default_factory=list)
    numbers: set[str] = field(default_factory=set)
    # Comparison tokens add equivalence hints for dimension spellings such as
    # 10 cm x 10 cm (4 in x 4 in) and 4 x 4. The display/relationship key
    # remains based on the original conservative tokens above.
    matching_tokens: list[str] = field(default_factory=list)


def _dimension_value(token: str) -> tuple[float, str | None] | None:
    match = _NUMERIC_TOKEN_RE.match(token)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit in _LENGTH_UNITS_INCHES:
        value *= _LENGTH_UNITS_INCHES[unit]
    return value, unit


def _dimension_token(left: str, right: str) -> str | None:
    """Return a stable token for a two-dimensional length expression.

    Unitless dimensions are kept exact. Explicit metric/imperial dimensions
    are rounded to the nearest quarter-inch so common printed equivalents
    (10 cm and 4 in; 5 cm and 2 in) share a fuzzy comparison hint. Original
    numeric tokens remain available to the numeric conflict guard.
    """
    a, b = _dimension_value(left), _dimension_value(right)
    if a is None or b is None:
        return None
    av, au = a
    bv, bu = b
    if au is None and bu is None:
        return f"DIM_{av:.2f}X{bv:.2f}"
    if au not in _LENGTH_UNITS_INCHES or bu not in _LENGTH_UNITS_INCHES:
        return None
    def canonical_length(value: float) -> float:
        # Preserve small diameters/gauges precisely enough for 0.018 in and
        # 0.46 mm to meet, while using quarter-inch tolerance for kit sizes.
        return round(value, 3) if abs(value) < 1 else round(value * 4) / 4

    av, bv = canonical_length(av), canonical_length(bv)
    return f"DIM_{av:.2f}X{bv:.2f}"


def _matching_tokens(tokens: list[str]) -> list[str]:
    """Add canonical dimension tokens without discarding original evidence."""
    out: list[str] = list(tokens)
    for i, left in enumerate(tokens):
        if _dimension_value(left) is None:
            continue
        # OCR and label prose sometimes inserts a qualifier before the
        # multiplication sign: `0.018IN OD X 50CM`. Treat that as the same
        # dimension spelling as `0.018IN X 50CM`.
        for j in range(i + 1, min(i + 4, len(tokens))):
            if tokens[j] != "X" or j + 1 >= len(tokens):
                continue
            dimension = _dimension_token(left, tokens[j + 1])
            if dimension is not None:
                out.append(dimension)
                break
    # A label commonly prints the same dimension in metric and imperial. One
    # canonical token is enough to reward equivalent wording without hiding
    # dimensions that use an intervening qualifier such as "OD".
    return list(dict.fromkeys(out))


def _singularize(token: str) -> str:
    if not token.isalpha() or len(token) <= 3 or token in _SINGULAR_EXCEPTIONS:
        return token
    if token.endswith("SS") or not token.endswith("S"):
        return token
    if token.endswith("IES"):
        return token[:-3] + "Y"
    if token.endswith(("XES", "CHES", "SHES", "SSES")):
        return token[:-2]
    return token[:-1]


def normalize(text: str) -> NormalizedText:
    s = text.translate({ord(c): None for c in _TRADEMARK_CHARS})
    s = _TEXT_TRADEMARK_RE.sub(r"\1", s)
    s = unicodedata.normalize("NFKC", s)
    s = s.translate({ord(c): "-" for c in _DASHES})
    s = s.upper()
    s = re.sub(r"\bW/O\b", "WITHOUT", s)
    s = re.sub(r"\bW/", "WITH ", s)
    s = _PERCENT_RE.sub(r"\1%", s)
    s = _UNIT_RE.sub(r"\1\2", s)
    s = _TRAILING_ZERO_RE.sub(r"\1", s)
    s = _DIM_RE.sub(r"\1 X \2", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _STRAY_DOT_RE.sub(" ", s)
    tokens = [ABBREVIATIONS.get(t, t) for t in s.split() if t != "TM"]
    tokens = [_singularize(t) for t in tokens]
    normalized = " ".join(tokens)
    numeric_tokens = [t for t in tokens if _NUMERIC_TOKEN_RE.match(t)]
    numbers = {_NUMERIC_TOKEN_RE.match(t).group(1) for t in numeric_tokens}
    matching_tokens = _matching_tokens(tokens)
    return NormalizedText(
        raw=text,
        normalized=normalized,
        tokens=tokens,
        sorted_key=" ".join(sorted(tokens)),
        numeric_tokens=numeric_tokens,
        numbers=numbers,
        matching_tokens=matching_tokens,
    )
