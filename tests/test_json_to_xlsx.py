import json

import pandas as pd

import json_to_xlsx


def test_convert_columns_order(tmp_path):
    src = tmp_path / "gen.json"
    records = [{"ID": 1, "Время создания": "2026-01-01", "Q": "Да", "Возраст": 30}]
    src.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.xlsx"

    json_to_xlsx.convert(src, out)

    df = pd.read_excel(out)
    assert list(df.columns[:2]) == ["ID", "Время создания"]
    assert len(df) == 1

    # Автоподбор ширины: колонка «Время создания» (15 символов) шире заголовка
    from openpyxl import load_workbook
    ws = load_workbook(out).active
    widths = {c: ws.column_dimensions[c].width
              for c in ("A", "B", "C")}
    assert widths["B"] is not None and widths["B"] >= len("Время создания") + 2
