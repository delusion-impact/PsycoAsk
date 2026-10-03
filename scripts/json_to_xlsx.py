import json
import pandas as pd
from pathlib import Path

from paths import GENERATED_JSON, GENERATED_XLSX, stamped


def convert():
    with open(GENERATED_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # Восстанавливаем порядок столбцов: ID и Время создания первыми
    priority_cols = ["ID", "Время создания"]
    other_cols = [c for c in df.columns if c not in priority_cols]
    df = df[priority_cols + other_cols]

    out_path = stamped(GENERATED_XLSX)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False, engine="openpyxl")
    print(f"✅ Excel файл создан: {out_path} ({len(df)} строк)")


if __name__ == "__main__":
    convert()