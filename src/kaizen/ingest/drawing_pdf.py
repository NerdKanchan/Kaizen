"""Parser for packaging drawings (text or scanned PDF): title block and EN/ES callouts.

A drawing is a PRESENCE source, not a quantity source; callouts carry no quantity. Cavity labels, notes and the
title block are noise. EN/ES pairs are one callout: the English text is the description, Spanish is kept as
evidence in `attributes.es_text`. Conditional callouts '(IF APPLICABLE PER BOM)' are flagged, not dropped.
"""

import re
import statistics
import unicodedata
from functools import lru_cache
from pathlib import Path

import pymupdf

from kaizen.ingest.hashing import document_id, sha256_file
from kaizen.ingest.ocr import ocr_available, ocr_page, ocr_words
from kaizen.ingest.pdf_words import Word, extract_words, group_lines, line_bbox, line_text, split_line_by_gaps
from kaizen.models import DocType, Document, DocumentItem, Evidence, ItemCategory

PARSER_NAME = "drawing_pdf"
PARSER_VERSION = "2"

ES_MARKERS = set(
    """CON DE DEL LA EL LOS LAS PARA SEGUN SI O Y EN UN UNA TUBO AGUJA JERINGA JERINGAS TIJERAS ALAMBRE GUIA CINTA METRICA
    BANDEJA ETIQUETA TAPAS TAPA EXTREMO CAVIDAD CAVIDADES ESCALPELO PAJILLA FILTRO SEGURIDAD CATETER DENTRO PORTA NAVAJA
    INTRODUCTORA INTRODUCTOR MICROINTRODUCTOR PROTECTOR PROTECTORA CORTE DISPOSITIVO APLICA BILLETE MATERIALES COLOCAR
    CUALQUIERA PINZAS VISTA ALTERNA SENCILLO COLGANTE TOALLA ABSORBENTE MASCARILLA GUANTES GASA VENDA TORNIQUETE SOPORTE
    REMOTO APOSITO ADHESIVO TOALLITA ELECTRODOS CABLES BANDA ELASTICA AZUL RECORTE CAMPO FENESTRADO BISTURI DILATADOR
    LIDOCAINA AMPOLLA SOLUCION SALINA CLORURO SODIO APLICADOR ASPIRACION TIRAS QUIRURGICA MEDICION CUBIERTA CORRESPONDE
    INDICADAS SOLAMENTE ORDEN TRABAJO APLICABILIDAD CANTIDAD COMPONENTE CONTRARIO ESPECIFIQUE MENOS LUBRICANTE GEL
    SENSOR HIPODERMICA LUMEN DOBLE ESTILETE LAVADO ESTABILIZACION POSICIONAMIENTO""".split()
)
EN_MARKERS = set(
    """WITH OR IF PER THE AND FOR TUBE TUBING NEEDLE SYRINGE SYRINGES SCISSORS WIRE GUIDE TAPE MEASURE TRAY LABEL CAPS
    CAP END HOLDER STRAW FILTER SAFETY CATHETER INSIDE PROTECTIVE FORCEPS DEVICE TRIMMING SHARP APPLICABLE BOM PLACE
    EITHER CAVITY INTRODUCER MICROINTRODUCER SCALPEL TOWEL ABSORBENT MASK GLOVES GAUZE DRAPE TOURNIQUET DRESSING WIPE
    ALCOHOL ELECTRODES LEADS BAND ELASTIC BLUE REMOTE CONTROL STRIPS SURGICAL MEASURING LIDOCAINE AMPULE SOLUTION SALINE
    APPLICATOR ASPIRATION GUIDEWIRE DILATOR STABILIZATION HYPODERMIC JELLY LUBRICATING PICC STYLET FUNNEL ASSEMBLY
    FENESTRATED ADHESIVE ISOPROPYL SODIUM CHLORIDE NITINOL STRAIGHT TIP BENDABLE VESSEL POSITIONING SYSTEM NEEDLES""".split()
)
_NOISE_RE = re.compile(
    r"^(NOTES?|NOTAS?)\b|^CAVITY\b|^CAVIDAD\b|^TOLERANCES?\b|^INCHES\b|^ANGLES\b|^THIRD ANGLE|^UNLESS OTHERWISE|^INTERPRET DRAWING|^NOTICE:|^UNAUTHORIZED|"
    r"^DRAWING NO|^SCALE\b|^DO NOT SCALE|^SHEET\b|^TITLE\b|^SIZE\b|^PART NO|^REV\.|^DWN\b|^CHK\b|^Checked by|^BD$|^\d+\.\s|^\.?X{1,3}\s*±|^ALTERNATIVE VIEW|^ALTERNATE UNITS|^VISTA ALTERNA|"
    r"^[A-Z .]+,\s*(MEXICO|USA|MX)$|^DWG\d{5,}\b|^\d{1,3}$|^\s*(FOR COMPONENT|LA ORDEN|PARA LA COLOCACION)",
    re.IGNORECASE,
)
_COND_EN = re.compile(r"\(\s*(?:IF|WHEN) APPLICABLE(?:\s+(?:AS\s+)?PER BOM)?\s*\)", re.IGNORECASE)
_PLACEMENT_RE = re.compile(r"\(\s*(PLACE IN [^)]*)\)", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_DRAWING_NO_RE = re.compile(r"DRAWING NO\.?\s*([A-Z0-9][A-Z0-9\-]{4,})", re.IGNORECASE)
_DWG_RE = re.compile(r"\b(DWG[0-9]{5,})\b")
_REV_RE = re.compile(r"(?<![A-Z])REV\.?\s*([A-Z0-9]{1,3})(?![A-Z0-9])")
_TITLE_RE = re.compile(r"\bTITLE\s*\n?\s*([^\n]+)")
_PLANT_RE = re.compile(r"^([A-Z][A-Z .]{2,},\s*(?:MEXICO|USA|PUERTO RICO|MX))$", re.MULTILINE)

_EXTRA_EN = set("PROTECTIVE HOLDER MAGNETS AMPULE BREAKER REMOTE COVER ELASTIC BANDS DRESSING COMPONENTS BAGGED SECUREMENT CONNECTOR ANCHOR BIOPATCH IV PICC MAX BARRIER POWERHOHN GLOVE WALLET ITEMS CHLORAPREP TINTED STICKER SUTURE WING FULL BODY GOWN CSR WRAP TUCK ECG ELECTRODE ELECTRODES LEAD ASSEMBLY SENSOR FFS POUCH INSERT SPACER SHIP CASE LITERATURE ELECTRONIC LABELING NOTICE GENERIC INFO SIDE TRIMMING FIRST SECOND FOLD TOP LOWER STEP PLACE WRAPPED ONTO TOP STACK BAG ZIP CLOSED INTO AS PRINT FACING UP TIP BOTH ALWAYS REFER WORK ORDER COMPONENT APPLICABILITY QUANTITY CORRECT PLACEMENT IMAGES REFERENCE ONLY CAN DIFFERENT PLEASE NO LIDOCAINE SALINE AND WHEN".split())
_EXTRA_ES = set("SUJETADOR PROTECTOR COLGANTE METRICA MEDICA IMANES CUBIERTA REMOTA BANDAS ELASTICAS BOLSA HULE ESPUMA ROMPEDOR AMPOLLETA VENDAJE EMBOLSADOS ASEGURAMIENTO ALA SUTURA CONECTOR FIJADORA TOALLA ALCOHOL SABANA COFIA MASCARA ARTICULOS ESTUCHE GUANTE TINTA ENVUELTA ENSAMBLAJE CABLE ELECTRODOS INSERTO ESPACIADOR CAJA ENVIO ETIQUETADO ELECTRONICO SUPERIOR INFERIOR APILAMIENTO GENERICA UNITARIA LATERAL PASO DOBLEZ PRIMER SEGUNDO BANDEJA COLOCAR ORDEN TRABAJO APLICABILIDAD CANTIDAD IMAGENES REFERENCIA SOLAMENTE COMPONENTES DIFERENTES FAVOR SIEMPRE BATA AMBOS PUNTA SOBRE ENVOLVER MUESTRA COMO DIAGRAMA DOBLADO ENVOLTURA COLOCADA AVISO CUANDO APLIQUE".split())
_VOCAB = EN_MARKERS | ES_MARKERS | _EXTRA_EN | _EXTRA_ES


@lru_cache(maxsize=2048)
def _unfuse_token(token: str) -> str:
    """Split only fully explainable all-caps OCR joins; unknown identifiers stay verbatim."""
    if token in _VOCAB or len(token) < 6 or not token.isalpha() or not token.isupper():
        return token
    parts: dict[int, list[str]] = {len(token): []}
    for i in range(len(token) - 1, -1, -1):
        candidates = [[token[i:j], *parts[j]] for j in range(i + 1, len(token) + 1) if j in parts and token[i:j] in _VOCAB]
        if candidates:
            parts[i] = min(candidates, key=len)
    return " ".join(parts[0]) if 0 in parts else token


def _clean_ocr_line(text: str) -> str:
    return re.sub(r"[A-Z]{6,}", lambda m: _unfuse_token(m.group()), text)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def is_spanish_line(line: str) -> bool:
    if any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", line)) or "Ñ" in line.upper():
        return True
    tokens = re.findall(r"[A-Z]+", _clean_ocr_line(_strip_accents(line).upper()))
    if tokens and tokens[0] in {"SABANA", "CATETER", "BOLSA", "BATA", "ELECTRODOS", "CUBIERTA", "ETIQUETA", "COLOCAR", "ENVOLVER", "SUJETADOR", "ENSAMBLAJE", "INSERTO", "PASO", "LADO"}:
        return True
    if any(t in {"COLOCADA", "ENVUELTA", "ENVOLTURA", "COLOCACION", "MUESTRA"} for t in tokens):
        return True
    es = sum(1 for t in tokens if t in ES_MARKERS | _EXTRA_ES)
    en = sum(1 for t in tokens if t in EN_MARKERS | _EXTRA_EN)
    return es > 0 and es >= en


def _clusters(lines: list[list[Word]]) -> list[list[list[Word]]]:
    heights = [max(w.y1 for w in l) - min(w.y0 for w in l) for l in lines] or [7.0]
    h = statistics.median(heights)
    clusters: list[list[list[Word]]] = []
    for line in sorted(lines, key=lambda l: (min(w.y0 for w in l), min(w.x0 for w in l))):
        x0, y0 = min(w.x0 for w in line), min(w.y0 for w in line)
        homes = []
        for c in clusters:
            last = c[-1]
            last_y0, last_y1 = min(w.y0 for w in last), max(w.y1 for w in last)
            # glyph boxes of consecutive lines overlap slightly (box height > line step), so a small negative
            # gap is normal; a gap wider than ~1.25 line heights starts a new callout
            right = max(w.x1 for w in line)
            last_left, last_right = min(w.x0 for w in last), max(w.x1 for w in last)
            center_delta = abs((x0 + right - last_left - last_right) / 2)
            aligned = abs(last_left - x0) <= 14 or abs(last_right - right) <= 14 or center_delta <= 18
            # Centred and right-aligned bilingual callouts are common in real drawings.
            # A new English label after a Spanish translation starts another callout.
            current_text = _clean_ocr_line(line_text(line))
            new_callout = is_spanish_line(line_text(last)) and not is_spanish_line(current_text) and not current_text.startswith(("(", '"', "'")) and not re.search(r'MATERIALES|BOM"?\)', current_text)
            if aligned and not new_callout and y0 > last_y0 and y0 - last_y1 <= 1.25 * h:
                homes.append((center_delta, c))
        home = min(homes, key=lambda entry: entry[0])[1] if homes else None
        if home is None:
            clusters.append([line])
        else:
            home.append(line)
    return clusters


def _header(text: str) -> dict:
    header: dict = {}
    flat = " ".join(text.split())
    if m := _DRAWING_NO_RE.search(flat):
        header["drawing_number"] = m.group(1).upper()
    elif m := _DWG_RE.search(flat):
        header["drawing_number"] = m.group(1)
    if m := _REV_RE.search(flat):
        header["revision"] = m.group(1)
    if m := _TITLE_RE.search(text):
        header["title"] = m.group(1).strip()
    if m := _PLANT_RE.search(text):
        header["plant"] = m.group(1).strip()
    return header


def parse_drawing_pdf(path: Path | str) -> Document:
    path = Path(path)
    sha = sha256_file(path)
    doc_id = document_id("dwg", sha, path)
    pdf = pymupdf.open(path)
    header: dict = {}
    items: list[DocumentItem] = []
    warnings: list[str] = []
    n_callouts = 0
    page_methods = []
    header["pages"] = len(pdf)
    for page in pdf:
        page_no = page.number + 1
        text = page.get_text()
        for k, v in _header(text).items():
            header.setdefault(k, v)
        words = extract_words(page)
        page_method = "pdf_text"
        if not words:
            if not ocr_available():
                warnings.append(f"page {page_no}: no extractable text and no OCR engine; install Tesseract or kaizen-crosscheck[ocr] — page skipped")
                page_methods.append("none")
                continue
            try:
                result = ocr_page(page)
                words = ocr_words(result)
                page_method = "ocr"
                header["ocr_engine"] = result.engine
                warnings.append(f"page {page_no}: OCR ({result.engine}, {result.dpi} dpi), {len(words)} words — verify callouts against the image")
            except Exception as exc:
                warnings.append(f"page {page_no}: OCR failed ({type(exc).__name__}); page skipped")
                page_methods.append("none")
                continue
        page_methods.append(page_method if words else "none")
        raw_lines = group_lines(words, y_tol=2.5)
        heights = [max(w.y1 for w in l) - min(w.y0 for w in l) for l in raw_lines] or [7.0]
        gap = 2.5 * statistics.median(heights)
        lines = [frag for l in raw_lines for frag in split_line_by_gaps(l, gap)]
        _spatial_header(page, lines, header, page_method, warnings)
        # Notes are preserved in the header, never treated as component callouts.
        body, note_lines = _split_notes(lines, page)
        page_notes = [line_text(l) for l in note_lines]
        # OCR also reads the printing inside product photographs. On a bilingual sheet a real callout carries
        # its translation, so unpaired English is rejected there; an English-only sheet keeps its callouts.
        bilingual = page_method == "ocr" and any(is_spanish_line(line_text(l)) for l in body)
        if page_notes:
            header.setdefault("notes", []).append({"page": page_no, "text": "\n".join(page_notes)})
            if "IMAGESFORREFERENCEONLY" in re.sub(r"\W", "", " ".join(page_notes).upper()):
                header["reference_only"] = True
        for cluster in _clusters(body):
            raw_texts = [line_text(l) for l in cluster]
            texts = [_clean_ocr_line(t) for t in raw_texts] if page_method == "ocr" else raw_texts
            if any(_NOISE_RE.search(t.strip()) for t in texts):
                continue
            en: list[str] = []
            es: list[str] = []
            for t in texts:
                # a callout is English lines followed by their Spanish translation; once Spanish starts, the
                # remaining lines (including marker-less continuations such as '"BOM")') belong to it
                if es or is_spanish_line(t) or (en and t.strip() == en[-1].strip()):
                    es.append(t)
                else:
                    en.append(t)
            en_text = " ".join(en).strip()
            if not en_text:
                continue
            # OCR inside the product photographs is evidence on the image, not a callout.
            # Real raster callouts use a paired translation; keep unpaired text as a warning.
            if bilingual and not es and en_text not in {"BIOPATCH", "CHLORAPREP"} and not _is_instruction(en_text):
                if re.search(r"[A-Z]{3,}", en_text) and any(t in EN_MARKERS | _EXTRA_EN for t in en_text.split()):
                    warnings.append(f"page {page_no}: unpaired OCR text not accepted as callout: {en_text[:100]}")
                continue
            conditional = bool(_COND_EN.search(en_text))
            conditional = conditional or bool(re.search(r"\(\s*IF APPLICABLE(?: AS)? PER BOM[,)]", en_text, re.I))
            en_text = _COND_EN.sub("", en_text)
            placement = None
            if m := _PLACEMENT_RE.search(en_text):
                placement = m.group(1).strip()
                en_text = _PLACEMENT_RE.sub("", en_text)
            en_text = " ".join(en_text.split()).strip(" ,;")
            if not en_text or not re.search(r"[A-Z]{2,}", en_text):
                continue
            es_text = " ".join(_PAREN_RE.sub("", " ".join(es)).split())
            depicted_count = None
            if m := re.search(r"\s*\((\d+)\)$", en_text):
                depicted_count = m.group(1)
                en_text = en_text[:m.start()].strip()
            n_callouts += 1
            bbox = line_bbox([w for l in cluster for w in l])
            items.append(
                DocumentItem(
                    id=f"{doc_id}:c{n_callouts}", doc_id=doc_id, doc_type=DocType.DRAWING, sku=header.get("drawing_number"), description=en_text, quantity=None,
                    category=ItemCategory.PHYSICAL_COMPONENT, category_reason="drawing callout (presence only; the drawing is not a quantity source)",
                    attributes={"kind": "instruction" if _is_instruction(en_text) else "callout", "es_text": es_text, "conditional": conditional, "placement": placement, "depicted_count": depicted_count, "callout_index": n_callouts, "sheet": page_no},
                    extraction_confidence=min(w.confidence for l in cluster for w in l),
                    evidence=Evidence(file=str(path), file_sha256=sha, page=page_no, bbox=bbox, raw_text=" / ".join(raw_texts), locator=f"sheet {page_no}, callout {n_callouts}", extraction_method=page_method),
                )
            )
    pdf.close()
    header["extraction_method"] = page_methods[0] if len(set(page_methods)) == 1 else "mixed"
    header["unreadable_pages"] = [i + 1 for i, method in enumerate(page_methods) if method == "none"]
    if not items and not any("no extractable" in w for w in warnings):
        warnings.append("no callouts found on the drawing")
    if "drawing_number" not in header:
        warnings.append("drawing number not found in title block")
    return Document(id=doc_id, doc_type=DocType.DRAWING, path=str(path), sha256=sha, sku=header.get("drawing_number"), header=header, items=items, parser_name=PARSER_NAME, parser_version=PARSER_VERSION, warnings=warnings)


def _top(line: list[Word]) -> float:
    return min(w.y0 for w in line)


def _split_notes(lines: list[list[Word]], page) -> tuple[list[list[Word]], list[list[Word]]]:
    """Separate note text from callout candidates.

    By drafting convention the notes sit with the title block along the bottom of the sheet, so a
    NOTES/NOTAS heading in the lower part of the sheet closes the callout area (the title block beside
    it is dropped). A heading higher up owns only the lines stacked directly beneath it, so a notes block
    near the top never hides the callouts below it."""
    headings = [l for l in lines if re.match(r"^(NOTES?|NOTAS?)\b", line_text(l), re.I)]
    cutoff = min((_top(h) for h in headings if _top(h) >= page.rect.height * 0.6), default=page.rect.height)
    notes = [l for l in lines if _top(l) >= cutoff and max(w.x1 for w in l) < page.rect.width * 0.6]
    taken: set[int] = set()
    for heading in sorted((h for h in headings if _top(h) < cutoff), key=_top):
        if id(heading) in taken:
            continue
        left, height = min(w.x0 for w in heading), max(w.y1 for w in heading) - _top(heading)
        bottom = max(w.y1 for w in heading)
        stack = [heading]
        for line in sorted(lines, key=_top):
            if id(line) in taken or line is heading or _top(line) <= _top(heading) or _top(line) >= cutoff:
                continue
            if not left - 10 <= min(w.x0 for w in line) <= left + 40:
                continue
            if _top(line) - bottom > 2 * height:
                break
            stack.append(line)
            bottom = max(bottom, max(w.y1 for w in line))
        taken.update(id(l) for l in stack)
        notes = stack + notes
    body = [l for l in lines if _top(l) < cutoff and id(l) not in taken]
    return body, notes


def _is_instruction(text: str) -> bool:
    return bool(re.match(r"^(?:PLACE|STEP|WRAP|FOR CORRECT|CORRECT PLACEMENT|FIRST FOLD|SECOND FOLD|TOP SIDE|LOWER SIDE|TRAY WRAPPED|WRAPPED GOWN|THREE KITS|ALL LITERATURE|GLOVE WALLET ITEMS|GOWN CSR WRAP|BAGGED DRESSING|DRESSING COMPONENTS|BAG WITH DRESSING|PICC OR POWERHOHN)", text, re.I))


def _spatial_header(page, lines, header, method, warnings):
    """Read stacked title-block cells, including a standalone revision digit."""
    for line in lines:
        text = line_text(line)
        if m := _DWG_RE.search(text):
            header.setdefault("drawing_number", m.group(1))
            header.setdefault("identity_evidence", {"page": page.number + 1, "bbox": line_bbox(line).model_dump(), "raw_text": text, "extraction_method": method})
            header.setdefault("identity_confidence", min(w.confidence for w in line))
        if m := _PLANT_RE.match(text):
            header.setdefault("plant", m.group(1).strip())
        if "title" not in header and min(w.y0 for w in line) > page.rect.height * 0.75 and re.fullmatch(r"[A-Z ]+ASSEMBLY", text):
            header["title"] = text
        if any(w.text.upper() == "TITLE" for w in line) and "title" not in header:
            line = [w for w in line if w.text.upper() == "TITLE"]
            candidates = [l for l in lines if min(w.y0 for w in l) >= max(w.y1 for w in line) and min(w.y0 for w in l) - max(w.y1 for w in line) < 25 and min(w.x0 for w in l) >= min(w.x0 for w in line) - 5]
            if candidates:
                header["title"] = line_text(min(candidates, key=lambda l: min(w.y0 for w in l)))
        for word in line:
            if word.text.upper().rstrip(".") != "REV" or "revision" in header:
                continue
            candidates = [w for l in lines for w in l if abs(w.cx - word.cx) < 12 and 0 < w.cy - word.cy < 25 and re.fullmatch(r"[A-Z0-9]{1,3}", w.text)]
            if candidates:
                candidate = min(candidates, key=lambda w: w.cy)
                header["revision"] = candidate.text
                header["revision_confidence"] = candidate.confidence
                header["revision_evidence"] = {"page": page.number + 1, "bbox": line_bbox([candidate]).model_dump(), "raw_text": candidate.text, "extraction_method": method}
            elif method == "ocr":
                # Small isolated revision digits are often missed by text detectors. Read
                # the cell directly, retaining the crop as evidence and its confidence.
                rect = pymupdf.Rect(word.x0 + 4, word.y1 + 3, word.x1 + 6, min(word.y1 + 15, page.rect.height))
                try:
                    result = ocr_page(page, dpi=400, clip=rect, single_line=True)
                    raw_value = "".join(w[4] for w in result.words).strip()
                    value = unicodedata.normalize("NFKC", raw_value)
                    if re.fullmatch(r"[A-Z0-9]{1,3}", value):
                        header["revision"] = value
                        header["revision_confidence"] = min(w[5] for w in result.words)
                        header["revision_evidence"] = {"page": page.number + 1, "bbox": dict(zip(("x0", "y0", "x1", "y1"), rect)), "raw_text": raw_value, "extraction_method": "ocr"}
                        if header["revision_confidence"] < 0.7:
                            warnings.append(f"page {page.number + 1}: drawing revision {value} has low OCR confidence ({header['revision_confidence']:.2f}) — verify the title block")
                except Exception as exc:
                    warnings.append(f"page {page.number + 1}: revision cell OCR failed ({type(exc).__name__})")
