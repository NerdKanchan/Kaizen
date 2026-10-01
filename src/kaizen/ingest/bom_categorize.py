"""Rule-based categorisation of BOM lines. Explainable: every answer comes with the rule that produced it."""

import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from kaizen.models import ItemCategory

CATEGORIZER_VERSION = "3"
_RULES_PATH = Path(__file__).with_name("bom_category_rules.json")


@lru_cache(maxsize=1)
def load_rules(path: Path | None = None) -> dict[str, Any]:
    with open(path or _RULES_PATH, encoding="utf-8") as fh:
        rules = json.load(fh)
    for rule in rules["keyword_rules"]:
        rule["_rx"] = re.compile(rule["pattern"], re.IGNORECASE)
    return rules


def categorize(
    item_number: str | None, description: str, quantity: Decimal | None, rules: dict[str, Any] | None = None
) -> tuple[ItemCategory, str]:
    rules = rules or load_rules()
    desc = description.upper()
    for rule in rules["keyword_rules"]:
        m = rule["_rx"].search(desc)
        if m:
            return ItemCategory(rule["category"]), f"{rule['reason']} (matched '{m.group(0)}')"
    if item_number:
        upper = item_number.upper()
        for rule in rules["prefix_rules"]:
            if upper.startswith(rule["prefix"]):
                return ItemCategory(rule["category"]), rule["reason"]
    if quantity is None:
        return ItemCategory.PHYSICAL_COMPONENT, "no non-physical rule matched; quantity unreadable, treated as physical so the reviewer sees it"
    if quantity > 0:
        return ItemCategory.PHYSICAL_COMPONENT, f"no non-physical rule matched and quantity {quantity} > 0"
    return ItemCategory.UNKNOWN, "no rule matched and quantity is zero"
