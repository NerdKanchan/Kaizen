"""Save exports atomically with business content stored as literal text."""

import os
import tempfile
from pathlib import Path


def save_workbook(workbook, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # These exports contain values, not computed cells. openpyxl otherwise treats
    # a source description or reviewer comment beginning with '=' as a formula.
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if cell.data_type in ('f', 'e'):
                    cell.data_type = 's'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.xlsx', delete=False) as file:
            temporary = Path(file.name)
        workbook.save(temporary)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def csv_text(value):
    # CSV cannot declare a text cell type. A leading apostrophe keeps spreadsheet
    # applications from executing formulas, including those preceded by whitespace.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value
