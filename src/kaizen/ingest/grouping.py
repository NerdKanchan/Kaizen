"""Groups parsed documents into SKU sets and reports coverage gaps.

Strategy: when the user organised files one set per folder (a folder holds exactly one BOM plus other
documents), the folder is the set. Otherwise (flat folders holding many BOMs) documents are grouped by product
family, derived from the BOM parent item / label REF. Both are deterministic; anomalies go into group warnings.
"""

import re
from collections import defaultdict
from pathlib import Path

from kaizen.models import DocType, Document, SkuGroup

_TYPE_ORDER = {DocType.BOM: 0, DocType.LABEL: 1, DocType.DRAWING: 2, DocType.PCO: 3}


def family_of(code: str | None) -> str:
    if not code:
        return ""
    m = re.match(r"^(\d+)", code.strip())
    return m.group(1) if m else code.strip()


def identity_key(code: str | None) -> str:
    """Return the stable numeric product identity shared by BOM parents and label REFs."""
    return family_of(code)


def group_by_sku(documents: list[Document]) -> list[SkuGroup]:
    documents = [d for d in documents if d.doc_type is not DocType.PCO]  # a PCO spans many SKUs; handled batch-wide
    folder_docs: dict[Path, int] = defaultdict(int)
    folder_boms: dict[Path, int] = defaultdict(int)
    for d in documents:
        folder_docs[Path(d.path).parent] += 1
        if d.doc_type is DocType.BOM:
            folder_boms[Path(d.path).parent] += 1
    buckets: dict[str, list[Document]] = defaultdict(list)
    for d in documents:
        folder = Path(d.path).parent
        if folder_docs[folder] >= 2 and folder_boms[folder] == 1:
            key = f"folder:{folder}"
        elif d.sku:
            key = f"family:{family_of(d.sku)}"
        else:
            key = f"file:{d.path}"
        buckets[key].append(d)
    groups: list[SkuGroup] = []
    for key in sorted(buckets):
        docs = sorted(buckets[key], key=lambda d: (_TYPE_ORDER.get(d.doc_type, 9), d.path))
        boms = [d for d in docs if d.doc_type is DocType.BOM]
        labels = [d for d in docs if d.doc_type is DocType.LABEL]
        sku = (boms[0].sku if boms and boms[0].sku else labels[0].sku if labels and labels[0].sku else key)
        family = family_of(sku)
        warnings: list[str] = []
        if not boms:
            warnings.append("no BOM document in this set")
        if not labels:
            warnings.append("no label document in this set")
        if len(boms) > 1:
            warnings.append(f"{len(boms)} BOM documents in one set: " + ", ".join(b.sku or b.path for b in boms))
        current_labels = [l for l in labels if l.header.get("revision_role", "current") != "old"]
        if len(current_labels) > 1:
            warnings.append(f"{len(current_labels)} current label documents in one set; each BOM is checked against each label")
        for lab in labels:
            if lab.sku and family and family_of(lab.sku) != family:
                warnings.append(f"label REF {lab.sku} does not belong to family {family} (BOM parent {sku}); REF/parent check will flag this")
        for d in docs:
            for w in d.warnings:
                warnings.append(f"{Path(d.path).name}: {w}")
        groups.append(SkuGroup(sku=sku, family=family, document_ids=[d.id for d in docs], warnings=warnings))
    return groups
