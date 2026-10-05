from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from openpyxl.utils import get_column_letter

from paths import GENERATED_JSON, GENERATED_XLSX, stamped

MAX_COL_WIDTH = 60


def autofit_columns(path) -> None:
    """Ширина столбцов по самому длинному значению с ограничением сверху.

    Буферная прибавка ~2 даёт тот же визуальный эффект, что автоподбор
    ширины в Excel, но без ручного прохода по каждому столбцу.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path)
    for ws in wb.worksheets:
        for column_cells in ws.columns:
            lengths = [len(str(cell.value)) for cell in column_cells
                       if cell.value is not None]
            if not lengths:
                continue
            width = min(max(lengths) + 2, MAX_COL_WIDTH)
            ws.column_dimensions[get_column_letter(column_cells[0].column)].width = width
    wb.save(path)


def convert(source=None, output=None) -> Path:
    """Выгружает сгенерированный JSON в Excel и возвращает путь к файлу.

    source/output необязательны: по умолчанию читается GENERATED_JSON, а
    результат получает штамп даты-времени в имени.
    """
    src_path = Path(source) if source else Path(GENERATED_JSON)
    with open(src_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # Восстанавливаем порядок столбцов: ID и Время создания первыми
    priority_cols = ["ID", "Время создания"]
    other_cols = [c for c in df.columns if c not in priority_cols]
    df = df[priority_cols + other_cols]

    out_path = Path(output) if output else stamped(GENERATED_XLSX)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False, engine="openpyxl")
    autofit_columns(out_path)
    print(f"✅ Excel файл создан: {out_path} ({len(df)} строк)")
    return out_path


if __name__ == "__main__":
    convert()