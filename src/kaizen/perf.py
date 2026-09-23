"""Performance harness: synthetic N-SKU datasets and timed phases (ingest / matching / report)."""

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import resource  # Unix-only; unavailable on Windows
except ImportError:
    resource = None

from kaizen.datasets.build import _bom_rows, _drawing_spec
from kaizen.datasets.drawing_docs import render_drawing_pdf
from kaizen.datasets.pdf_bom import BomSpec, render_bom_pdf
from kaizen.datasets.pdf_label import LabelSpec, render_label_pdf
from kaizen.datasets.scenarios import s01
from kaizen.models import Thresholds
from kaizen.pipeline import ingest_folder, run_checks
from kaizen.reporting.excel import write_report
from kaizen.terminology.store import RelationshipStore


@dataclass
class PerfMetrics:
    skus: int
    documents: int
    rows: int
    ingest_seconds: float
    matching_seconds: float
    report_seconds: float
    total_seconds: float
    peak_memory_mb: float | None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rows_per_second"] = round(self.rows / self.matching_seconds, 1) if self.matching_seconds else None
        d["seconds_per_sku"] = round(self.total_seconds / self.skus, 3) if self.skus else None
        return d


def build_perf_dataset(root: Path | str, skus: int) -> Path:
    """N clean SKUs of the golden family (BOM PDF, label PDF, drawing PDF each), distinct parent items."""
    root = Path(root)
    base = s01()
    for i in range(skus):
        parent = f"{5000000 + i}NS"
        ref = parent[:-2]
        folder = root / f"sku-{i + 1:03d}"
        spec = BomSpec(parent_item=parent, parent_description=base.parent_description, rows=_bom_rows(base))
        render_bom_pdf(spec, folder / "bom.pdf")
        render_label_pdf(LabelSpec(ref=ref, product_name=base.product_name, contents=[f"{l.label_qty} Each - {l.label_text}" for l in base.lines if l.label_text]), folder / "label.pdf")
        render_drawing_pdf(_drawing_spec(base), folder / "drawing.pdf")
    return root


def _peak_mb() -> float | None:
    if resource is None:
        return None
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024, 1)
    except Exception:
        return None


def measure(root: Path | str, out_dir: Path | None = None) -> PerfMetrics:
    root = Path(root)
    store = RelationshipStore.default()
    t0 = time.perf_counter()
    ing = ingest_folder(root)
    t1 = time.perf_counter()
    run = run_checks(ing, store, Thresholds())
    t2 = time.perf_counter()
    out = (out_dir or root / "_perf")
    write_report(run, out / "report.xlsx")
    t3 = time.perf_counter()
    return PerfMetrics(len(run.groups), len(run.documents), len(run.results), round(t1 - t0, 3), round(t2 - t1, 3), round(t3 - t2, 3), round(t3 - t0, 3), _peak_mb())


def run_series(root: Path | str, sizes: tuple[int, ...] = (8, 25, 50, 100)) -> list[PerfMetrics]:
    root = Path(root)
    out = []
    for n in sizes:
        ds = build_perf_dataset(root / f"perf-{n}", n)
        out.append(measure(ds))
    (root / "perf-results.json").write_text(json.dumps([m.to_dict() for m in out], indent=2))
    return out
