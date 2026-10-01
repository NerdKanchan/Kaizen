"""Identify protected Excel containers without attempting to unlock them."""

from pathlib import Path


def workbook_access_problem(path: Path | str) -> str | None:
    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xls"):
        return None
    with path.open("rb") as fh:
        prefix = fh.read(65536)
    if not prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return None
    if "DRMEncryptedTransform".encode("utf-16le") in prefix:
        return "Workbook is protected by a sensitivity label (rights management). An authorized user must open it in Excel and export a readable XLSX or CSV (an unprotected copy) where the document policy permits it."
    if "EncryptedPackage".encode("utf-16le") in prefix:
        return "Cannot read this encrypted Excel workbook. Supply an authorized unlocked XLSX or CSV export."
    return "Legacy Excel container; export a readable XLSX or CSV from Excel."
