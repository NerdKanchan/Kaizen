"""Groups parsed documents into SKU sets and reports coverage gaps.

Strategy: when the user organised files one set per folder (a folder holds exactly one BOM plus other
documents), the folder is the set. Otherwise (flat folders holding many BOMs) documents are grouped by product
family, derived from the BOM parent item / label REF. Both are deterministic; anomalies go into group warnings.
"""

import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
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
    # A delivered package often contains both SKU folders and identical copies in
    # type-specific folders. Prefer the explicit set; retain all files in the Run.
    duplicate_notes: dict[str, list[str]] = defaultdict(list)
    kept: list[Document] = []
    seen: dict[tuple, bool] = {}
    for d in sorted(documents, key=lambda d: (-(folder_docs[Path(d.path).parent] >= 2 and folder_boms[Path(d.path).parent] == 1), d.path)):
        key = (d.doc_type, d.sha256)
        explicit_set = folder_docs[Path(d.path).parent] >= 2 and folder_boms[Path(d.path).parent] == 1
        if d.doc_type is not DocType.DRAWING and key in seen and not (explicit_set and seen[key]):
            duplicate_notes[family_of(d.sku)].append(f"identical copy {d.path} retained as evidence; compared once")
            continue
        seen[key] = explicit_set
        kept.append(d)
    documents = kept
    folder_docs = Counter(Path(d.path).parent for d in documents)
    folder_boms = Counter(Path(d.path).parent for d in documents if d.doc_type is DocType.BOM)
    pdf_boms = [d for d in documents if d.doc_type is DocType.BOM and d.path.lower().endswith('.pdf')]
    kept = []
    for d in documents:
        if d.doc_type is DocType.BOM and d.header.get("parent_inferred_from") == "filename" and any(b.sku == d.sku and _bom_rows(b) == _bom_rows(d) for b in pdf_boms):
            duplicate_notes[family_of(d.sku)].append(f"matching spreadsheet export {d.path} retained as reference; PDF BOM compared once")
        else:
            kept.append(d)
    documents = kept
    folder_docs = Counter(Path(d.path).parent for d in documents)
    folder_boms = Counter(Path(d.path).parent for d in documents if d.doc_type is DocType.BOM)
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
    drawing_buckets = [key for key, docs in buckets.items() if all(d.doc_type is DocType.DRAWING for d in docs)]
    shared = [d for key in drawing_buckets for d in buckets[key]]
    shared_by_hash = {d.sha256: d for d in shared}
    if len(shared_by_hash) == 1:
        drawing = next(iter(shared_by_hash.values()))
        used = False
        for key, docs in buckets.items():
            if key not in drawing_buckets and any(d.doc_type is DocType.BOM for d in docs) and any(d.doc_type is DocType.DRAWING and d.sha256 == drawing.sha256 for d in docs):
                used = True
            if key not in drawing_buckets and any(d.doc_type is DocType.BOM for d in docs) and not any(d.doc_type is DocType.DRAWING for d in docs):
                docs.append(drawing)
                used = True
                bom = next(d for d in docs if d.doc_type is DocType.BOM)
                duplicate_notes[family_of(bom.sku)].append("one shared drawing supplied for the batch; applicability must be confirmed against each BOM")
        if used:
            for key in drawing_buckets:
                del buckets[key]
    groups: list[SkuGroup] = []
    for key in sorted(buckets):
        docs = sorted(buckets[key], key=lambda d: (_TYPE_ORDER.get(d.doc_type, 9), d.path))
        boms = [d for d in docs if d.doc_type is DocType.BOM]
        labels = [d for d in docs if d.doc_type is DocType.LABEL]
        sku = (boms[0].sku if boms and boms[0].sku else labels[0].sku if labels and labels[0].sku else key)
        family = family_of(sku)
        warnings: list[str] = list(duplicate_notes.get(family, []))
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


def _bom_rows(doc: Document) -> Counter:
    def sequence(value):
        try:
            return str(Decimal(value).normalize()) if value else ""
        except InvalidOperation:
            return value
    return Counter((i.item_number, i.description, i.quantity, i.uom, sequence(i.oper_seq), i.attributes.get("effective_from"), i.attributes.get("effective_thru")) for i in doc.items)
