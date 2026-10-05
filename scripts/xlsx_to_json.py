from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

from paths import INPUT_DIR, ROOT_DIR, SURVEY_JSON, ensure_dirs

ID_KEY = "ID"
EMPTY_HEADER = "Без названия"


def make_unique_names(raw_names: list[object]) -> list[str]:
    """Чистит заголовки и убирает дубли: 'Вопрос', 'Вопрос_2', 'Вопрос_3'."""
    counters: dict[str, int] = {}
    unique: list[str] = []

    for index, raw in enumerate(raw_names):
        if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
            name = ""
        else:
            name = str(raw).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"{EMPTY_HEADER}_{index + 1}"

        if name in counters:
            counters[name] += 1
            unique.append(f"{name}_{counters[name]}")
        else:
            counters[name] = 1
            unique.append(name)

    return unique


def normalize_value(value):
    """Строка -> обрезанная строка, пустая строка -> None."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    return value or None


def to_json_safe(value):
    """NaN/NaT -> None, иначе значение без изменений."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def coerce_id(value):
    """'2525161289.0' -> 2525161289, нечисловые значения остаются как есть."""
    if value is None or isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return value


def parse_xlsx_to_json(file_path: Path | str, output_path: Path | str | None = None) -> list[dict]:
    """Читает Excel и возвращает список словарей (по строке на респондента).

    Пустые ячейки и целые пустые строки отбрасываются, ID приводится к int,
    повторяющиеся заголовки получают суффиксы _2, _3.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    # Один проход по файлу: первая строка — заголовки, остальное — данные.
    # pandas сам разводит дубли заголовков как 'Вопрос.1', из-за чего
    # оригинальные имена теряются безвозвратно.
    raw = pd.read_excel(path, header=None, dtype=str)
    if raw.empty:
        raise ValueError(f"Лист пуст, нечего парсить: {path}")

    raw_names = raw.iloc[0].tolist()
    has_header_row = any(pd.notna(value) for value in raw_names)
    data = raw.iloc[1:] if has_header_row else raw
    df = data.reset_index(drop=True)
    if has_header_row and len(raw_names) == df.shape[1]:
        df.columns = make_unique_names(raw_names)
    else:
        df.columns = [str(col) for col in df.columns]

    # Обрезаем пробелы (normalize_value возвращает обрезанное значение —
    # именно его и сохраняем, а не исходное), пустые строки и NaN → None
    df = df.astype(object).map(normalize_value)
    df = df.where(df.notna(), None)
    df.dropna(how="all", inplace=True)

    records: list[dict] = []
    for row in df.to_dict(orient="records"):
        record = {key: to_json_safe(value) for key, value in row.items()}
        if ID_KEY in record:
            record[ID_KEY] = coerce_id(record[ID_KEY])
        records.append(record)

    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            # allow_nan=False: NaN в JSON невалиден, лучше упасть, чем записать мусор
            json.dump(records, f, ensure_ascii=False, indent=2, allow_nan=False)
        print(f"✅ Сохранено в {rel(out_path)} "
              f"({len(records)} записей, {len(df.columns)} столбцов)")

    return records


def rel(path: Path) -> str:
    """Путь относительно корня проекта — так короче в выводе."""
    try:
        return str(Path(path).resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    ensure_dirs()
    # Необязательный аргумент: путь к своей выгрузке вместо data/input/ref.xlsx
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT_DIR / "ref.xlsx"
    parse_xlsx_to_json(source, SURVEY_JSON)