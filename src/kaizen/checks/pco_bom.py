"""Check 4: PCO ↔ BOM. A PCO describes intended changes; the check asks whether each was applied to each
affected code's BOM. Coverage rows (is there a BOM for every affected code?) come first and block."""

from decimal import Decimal

from kaizen.checks.base import RECOMMENDED_ACTION, RowIdFactory, header_item, pair_token
from kaizen.ingest.pco import change_kind
from kaizen.ingest.quantity import parse_decimal
from kaizen.matching.ladder import MatchContext, MatchLadder
from kaizen.matching.normalize import normalize
from kaizen.models import CheckResult, CheckType, Classification, Discrepancy, DiscrepancyType, DocType, Document, DocumentItem, MatchLevel, Severity, Thresholds

CHECK_VERSION = "1"


def _disc(dtype: DiscrepancyType, severity: Severity, detail: str) -> Discrepancy:
    return Discrepancy(type=dtype, severity=severity, detail=detail, recommended_action=RECOMMENDED_ACTION.get(dtype, ""))


def _num(s: str | None) -> Decimal | None:
    return parse_decimal(s)


def _redline_hits(row: DocumentItem, text: str) -> bool:
    key = normalize(text).sorted_key
    return any(normalize(r.get("text", "")).sorted_key == key for r in row.attributes.get("redlines", []))


def _qty_seq_check(chg: DocumentItem, row: DocumentItem) -> list[str]:
    problems = []
    qp = _num(chg.attributes.get("qty_proposed"))
    if chg.attributes.get("qty_proposed") and qp is None:
        problems.append("proposed quantity is unreadable")
    if qp is not None and (row.quantity is None or row.quantity != qp):
        problems.append(f"quantity {row.quantity if row.quantity is not None else '?'} vs proposed {qp}")
    sp = _num(chg.attributes.get("seq_proposed"))
    if chg.attributes.get("seq_proposed") and sp is None:
        problems.append("proposed operation sequence is unreadable")
    if sp is not None:
        rs = _num(row.oper_seq)
        if rs is None or rs != sp:
            problems.append(f"oper seq {row.oper_seq or '?'} vs proposed {sp}")
    return problems


def run_pco_bom_check(pco: Document, boms: list[Document], ladder: MatchLadder, thresholds: Thresholds) -> list[CheckResult]:
    number = pco.header.get("pco_number") or pco.id
    ids = RowIdFactory(number, letter="P", pair=pair_token(pco.id, *sorted(b.id for b in boms)))
    boms_by_parent: dict[str, list[Document]] = {}
    for b in boms:
        if b.sku:
            boms_by_parent.setdefault(b.sku, []).append(b)
    codes = [i for i in pco.items if i.attributes.get("kind") == "affected_code"]
    changes = [i for i in pco.items if i.attributes.get("kind") == "change"]
    results: list[CheckResult] = []

    # coverage first — never silently skip a missing BOM
    for code_item in codes:
        code = code_item.item_number or ""
        found = boms_by_parent.get(code, [])
        if not found:
            detail = f"PCO {number} lists affected code {code} but no BOM with parent item {code} is in this set"
            results.append(CheckResult(row_id=ids.next(), sku=code, check=CheckType.PCO_BOM, role="coverage", source_a=code_item, source_b=None, classification=Classification.MISSING, match_level=MatchLevel.NONE, score=0.0, explanation=f"COVERAGE: {detail}", discrepancies=[_disc(DiscrepancyType.BOM_MISSING_FOR_AFFECTED_CODE, Severity.BLOCKER, detail)], requires_validation=True))
        elif len(found) > 1:
            files = ", ".join(b.path for b in found)
            results.append(CheckResult(row_id=ids.next(), sku=code, check=CheckType.PCO_BOM, role="coverage", source_a=code_item, source_b=header_item(found[0], "BOM"), classification=Classification.POTENTIAL, match_level=MatchLevel.NONE, score=0.0, explanation=f"COVERAGE: {len(found)} BOM documents share parent item {code} ({files}); every one is evaluated below — confirm which is current", requires_validation=True))
        else:
            bom = found[0]
            results.append(CheckResult(row_id=ids.next(), sku=code, check=CheckType.PCO_BOM, role="coverage", source_a=code_item, source_b=header_item(bom, "BOM"), classification=Classification.EXACT, match_level=MatchLevel.EXACT, score=1.0, explanation=f"COVERAGE: BOM for affected code {code} present ({bom.path}, {len(bom.items)} rows)"))

    for code_item in codes:
        code = code_item.item_number or ""
        for bom in boms_by_parent.get(code, []):
            active: dict[str, list[DocumentItem]] = {}
            inactive: dict[str, list[DocumentItem]] = {}
            for it in bom.items:
                if not it.item_number:
                    continue
                (active if it.is_active else inactive).setdefault(it.item_number, []).append(it)
            for chg in changes:
                results.append(_evaluate(chg, code, bom, active, inactive, ladder, ids, number))
    return results


def _pick_row(rows: list[DocumentItem], seq_text: str | None) -> tuple[DocumentItem | None, str]:
    """Choose the BOM row a change applies to when an item sits on several operation sequences."""
    if len(rows) == 1:
        return rows[0], ""
    seq = _num(seq_text)
    if seq is not None:
        hits = [r for r in rows if _num(r.oper_seq) == seq]
        if len(hits) == 1:
            return hits[0], ""
        if len(hits) > 1:
            return None, f"{len(hits)} rows share oper seq {seq} — reviewer to confirm"
        return rows[0], f" (no row at oper seq {seq}; item appears on seqs {', '.join(r.oper_seq or '?' for r in rows)})"
    seqs = ", ".join(r.oper_seq or "?" for r in rows)
    return None, f"item appears on {len(rows)} rows (oper seqs {seqs}) and the PCO does not say which — reviewer to confirm"


def _evaluate(chg: DocumentItem, code: str, bom: Document, active: dict[str, list[DocumentItem]], inactive: dict[str, list[DocumentItem]], ladder: MatchLadder, ids: RowIdFactory, number: str) -> CheckResult:
    a, p = chg.attributes.get("item_actual", ""), chg.attributes.get("item_proposed", "")
    kind, key = change_kind(a, p if chg.attributes.get("change_kind") != "DELETE" else "DELETE")
    chg.attributes.setdefault("change_kind", kind)
    chg.attributes.setdefault("change_key", key)
    label = f"PCO {number} {key} on BOM {code}"
    discrepancies: list[Discrepancy] = []
    classification = Classification.EXACT
    source_b: DocumentItem | None = None
    note = ""

    if kind == "DELETE":
        rows = active.get(a, [])
        row = rows[0] if rows else None
        if row is None:
            skipped = [w for w in bom.warnings if "skipped" in w.lower()]
            lookalikes = [it for its in active.values() for it in its if chg.description and ladder.match(chg.description, it.description, MatchContext(sku=code, doc_types=(DocType.PCO, DocType.BOM))).assignable]
            if a in inactive:
                old = inactive[a][0]
                note = f"item {a} is present only as an inactive row ({old.evidence.locator}, effective {old.attributes.get('effective_from', '?')} to {old.attributes.get('effective_thru', '?')}) — deletion applied"
            elif lookalikes:
                source_b, classification = lookalikes[0], Classification.POTENTIAL
                note = f"item {a} is not on the BOM by number, but '{lookalikes[0].description}' is still present as item {lookalikes[0].item_number} ({lookalikes[0].evidence.locator}) — confirm the deletion (variant item number?)"
            elif skipped:
                classification = Classification.POTENTIAL
                note = f"item {a} was not found, but BOM pages were skipped during extraction ({'; '.join(skipped)}) — deletion cannot be confirmed"
            else:
                note = f"item {a} is not on any BOM row (active or inactive) — deletion applied"
        elif any(str(r.get("text", "")).upper() in ("DELETE", "DELETED", "REMOVE") for r in row.attributes.get("redlines", [])):
            source_b, classification = row, Classification.POTENTIAL
            note = f"item {a} still printed at {row.evidence.locator} but a redline annotation marks it deleted — reviewer to confirm"
        else:
            source_b, classification = row, Classification.MISMATCH
            detail = f"item {a} still present at {row.evidence.locator} (qty {row.quantity}) although the PCO deletes it"
            discrepancies.append(_disc(DiscrepancyType.PCO_CHANGE_NOT_APPLIED, Severity.MAJOR, detail))
            note = detail
    elif kind == "ADD":
        row, pick_note = _pick_row(active.get(p, []), chg.attributes.get("seq_proposed")) if active.get(p) else (None, "")
        if row is None and active.get(p):
            source_b, classification = active[p][0], Classification.POTENTIAL
            note = f"item {p} present but {pick_note}"
        elif row is None:
            redlined = next((r for rs in active.values() for r in rs if _redline_hits(r, p)), None)
            if redlined is not None:
                source_b, classification = redlined, Classification.POTENTIAL
                note = f"item {p} not printed as a row, but a redline annotation on {redlined.evidence.locator} ({redlined.item_number}) reads {p} — reviewer to confirm the redline"
            else:
                classification = Classification.MISMATCH
                detail = f"item {p} ({chg.description}) is not in the BOM although the PCO adds it (qty {chg.attributes.get('qty_proposed') or '?'}, oper seq {chg.attributes.get('seq_proposed') or '?'})"
                discrepancies.append(_disc(DiscrepancyType.PCO_CHANGE_NOT_APPLIED, Severity.MAJOR, detail))
                note = detail
        else:
            source_b = row
            problems = _qty_seq_check(chg, row)
            if problems:
                classification = Classification.MISMATCH
                detail = f"item {p} present at {row.evidence.locator} but " + "; ".join(problems) + pick_note
                discrepancies.append(_disc(DiscrepancyType.PCO_QTY_SEQ_MISMATCH, Severity.MAJOR, detail))
                note = detail
            else:
                note = f"item {p} present at {row.evidence.locator} with proposed quantity and operation sequence — addition applied"
            discrepancies.extend(_desc_check(chg, row, ladder, code))
    elif kind == "SUBSTITUTE":
        old = active.get(a, [None])[0]
        new_rows = active.get(p, [])
        new, pick_note = (_pick_row(new_rows, chg.attributes.get("seq_proposed")) if new_rows else (None, ""))
        if new is None and new_rows:
            if old is None:
                source_b, classification = new_rows[0], Classification.POTENTIAL
                note = f"old item {a} absent; new item {p}: {pick_note}"
                return CheckResult(row_id=ids.next(), sku=code, check=CheckType.PCO_BOM, source_a=chg, source_b=source_b, classification=classification, match_level=MatchLevel.NONE, score=0.0, explanation=f"{label}: {note}", requires_validation=True)
            new = new_rows[0]
        if old is not None and new is None and _redline_hits(old, p):
            source_b, classification = old, Classification.POTENTIAL
            note = f"old item {a} at {old.evidence.locator} carries a redline annotation reading {p} — substitution applied by redline, reviewer to confirm"
        elif old is not None:
            source_b, classification = old, Classification.MISMATCH
            detail = f"old item {a} still present at {old.evidence.locator}" + ("" if new is not None else f"; new item {p} not found")
            discrepancies.append(_disc(DiscrepancyType.PCO_CHANGE_NOT_APPLIED, Severity.MAJOR, detail))
            note = detail
        elif new is None:
            classification = Classification.MISMATCH
            detail = f"old item {a} absent but new item {p} ({chg.description}) not found in the BOM"
            discrepancies.append(_disc(DiscrepancyType.PCO_CHANGE_NOT_APPLIED, Severity.MAJOR, detail))
            note = detail
        else:
            source_b = new
            problems = _qty_seq_check(chg, new)
            if problems:
                classification = Classification.MISMATCH
                detail = f"substitution applied ({a} → {p} at {new.evidence.locator}) but " + "; ".join(problems)
                discrepancies.append(_disc(DiscrepancyType.PCO_QTY_SEQ_MISMATCH, Severity.MAJOR, detail))
                note = detail
            else:
                note = f"old item {a} absent, new item {p} present at {new.evidence.locator} with proposed quantity and sequence — substitution applied"
            discrepancies.extend(_desc_check(chg, new, ladder, code))
    else:  # MODIFY
        rows = active.get(a, [])
        row, pick_note = _pick_row(rows, chg.attributes.get("seq_actual") or chg.attributes.get("seq_proposed")) if rows else (None, "")
        if row is None and rows:
            source_b, classification = rows[0], Classification.POTENTIAL
            note = f"item {a}: {pick_note}"
        elif row is None:
            classification = Classification.MISMATCH
            detail = f"item {a} to be modified is not in the BOM"
            discrepancies.append(_disc(DiscrepancyType.PCO_CHANGE_NOT_APPLIED, Severity.MAJOR, detail))
            note = detail
        else:
            source_b = row
            problems = _qty_seq_check(chg, row)
            qp = chg.attributes.get("qty_proposed", "")
            if problems and qp and _redline_hits(row, qp):
                classification = Classification.POTENTIAL
                note = f"item {a} at {row.evidence.locator}: printed values differ but a redline annotation reads {qp} — reviewer to confirm"
            elif problems:
                classification = Classification.MISMATCH
                detail = f"item {a} at {row.evidence.locator}: " + "; ".join(problems) + pick_note
                discrepancies.append(_disc(DiscrepancyType.PCO_QTY_SEQ_MISMATCH, Severity.MAJOR, detail))
                note = detail
            else:
                note = f"item {a} at {row.evidence.locator} carries the proposed quantity and sequence — modification applied"
    if classification is Classification.EXACT and (not bom.items or bom.header.get('unreadable_pages') or bom.header.get('unparsed_rows')):
        classification = Classification.POTENTIAL
        note += "; BOM extraction is incomplete — confirm against the source before clearing this change"
    requires = classification is not Classification.EXACT or bool(discrepancies)
    return CheckResult(
        row_id=ids.next(), sku=code, check=CheckType.PCO_BOM, source_a=chg, source_b=source_b, normalized_a=normalize(chg.description).normalized if chg.description else None,
        normalized_b=normalize(source_b.description).normalized if source_b and source_b.description else None, classification=classification,
        match_level=MatchLevel.EXACT if classification is Classification.EXACT else MatchLevel.NONE, score=1.0 if classification is Classification.EXACT else 0.0,
        explanation=f"{label}: {note}", discrepancies=discrepancies, requires_validation=requires,
    )


def _desc_check(chg: DocumentItem, row: DocumentItem, ladder: MatchLadder, code: str) -> list[Discrepancy]:
    if not chg.description or not row.description:
        return []
    out = ladder.match(chg.description, row.description, MatchContext(sku=code, doc_types=(DocType.PCO, DocType.BOM), item_number=row.item_number))
    if out.assignable:
        return []
    return [_disc(DiscrepancyType.DESC_MISMATCH, Severity.MINOR, f"PCO description '{chg.description}' does not match BOM description '{row.description}' for item {row.item_number} ({out.reason})")]
