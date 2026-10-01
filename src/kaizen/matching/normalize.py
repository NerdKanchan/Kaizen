"""Deterministic text normalisation. Conservative on purpose: it removes noise, never meaning.

Every transformation is listed here so a reviewer can read what "normalised" means.
"""

import re
import unicodedata
from dataclasses import dataclass, field

NORMALIZER_VERSION = "2"

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
}

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
    return NormalizedText(
        raw=text,
        normalized=normalized,
        tokens=tokens,
        sorted_key=" ".join(sorted(tokens)),
        numeric_tokens=numeric_tokens,
        numbers=numbers,
    )
