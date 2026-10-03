from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from paths import GENERATED_JSON, GENERATED_XLSX, stamped


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
    print(f"✅ Excel файл создан: {out_path} ({len(df)} строк)")
    return out_path


if __name__ == "__main__":
    convert()