from __future__ import annotations

from pathlib import Path

import pandas as pd

from paths import GENERATED_JSON, REPORT_XLSX, SURVEY_JSON, ensure_dirs, stamped

GENERATED_FILE = GENERATED_JSON
ORIGINAL_FILE = SURVEY_JSON  # Опционально, для сравнения
OUTPUT_XLSX = REPORT_XLSX

EXCLUDE_KEYS = {"ID", "Время создания"}

MALE_COLUMN = "Ваш пол / Мужской"
FEMALE_COLUMN = "Ваш пол / Женский"


def build_distribution_table(filepath):
    """Строит таблицу распределений: вопросы × варианты ответов (%)"""
    df = pd.read_json(filepath, orient='records')
    cols = [c for c in df.columns if c not in EXCLUDE_KEYS]

    rows = []
    for col in cols:
        # dropna=False — проценты считаем от всех записей вопроса, но пустые
        # ответы (None → NaN) в отчёт не попадают: без проверки pd.isna
        # подписью такого ответа становилась строка "nan"
        counts = df[col].value_counts(normalize=True, dropna=False)
        row = {"_question": col}
        for answer, freq in counts.items():
            if pd.isna(answer):
                continue
            row[str(answer)] = round(freq * 100, 1)
        rows.append(row)

    result = pd.DataFrame(rows).set_index("_question")
    result = result.fillna(0.0)
    return result[sorted(result.columns)]


def build_gender_table(orig_path, gen_path):
    """Строит таблицу баланса пола.

    Столбцы о поле опциональны: если в выгрузке их нет, лист остаётся пустым,
    а не роняет весь отчёт (в UI это отдельная выгрузка без вопроса о поле).
    """
    rows = []
    for label, path in [("Оригинал", orig_path), ("Генерация", gen_path)]:
        if not path or not Path(path).exists():
            continue
        df = pd.read_json(path, orient='records')
        if MALE_COLUMN not in df.columns and FEMALE_COLUMN not in df.columns:
            continue
        male = int(df[MALE_COLUMN].notna().sum()) if MALE_COLUMN in df.columns else 0
        female = int(df[FEMALE_COLUMN].notna().sum()) if FEMALE_COLUMN in df.columns else 0
        total = len(df)
        rows.append({
            "Источник": label,
            "Мужской": male,
            "Женский": female,
            "Всего": total,
            "% Мужской": round(male / total * 100, 1) if total else 0,
            "% Женский": round(female / total * 100, 1) if total else 0,
        })
    return pd.DataFrame(rows, columns=["Источник", "Мужской", "Женский",
                                       "Всего", "% Мужской", "% Женский"])


def apply_conditional_formatting(writer, sheet_name, df):
    """
    Добавляет цветовую шкалу к листу с распределениями.
    Исправлено для поддержки >26 столбцов.
    """
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter

    ws = writer.sheets[sheet_name]

    min_col = 2  # B (пропускаем столбец с названиями вопросов)
    max_col = ws.max_column
    min_row = 2  # пропускаем заголовок
    max_row = ws.max_row

    if max_col < min_col or max_row < min_row:
        print("⚠️ Нет данных для применения условного форматирования")
        return

    rule = ColorScaleRule(
        start_type='min', start_color='FFFFFF',
        mid_type='percentile', mid_value=50, mid_color='BDD7EE',
        end_type='max', end_color='4472C4'
    )

    # ✅ Используем get_column_letter вместо chr()
    start_cell = f"{get_column_letter(min_col)}{min_row}"
    end_cell = f"{get_column_letter(max_col)}{max_row}"
    cell_range = f"{start_cell}:{end_cell}"

    ws.conditional_formatting.add(cell_range, rule)

    # Ширина первого столбца (названия вопросов)
    ws.column_dimensions['A'].width = 60
    # Остальные столбцы — узкие
    for col_idx in range(min_col, max_col + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18


def build_report(generated=None, original=None, output=None) -> Path:
    """Отчёт Excel: распределения + баланс пола + легенда."""
    ensure_dirs()

    dist_gen = build_distribution_table(generated or GENERATED_FILE)
    gender = build_gender_table(original or ORIGINAL_FILE, generated or GENERATED_FILE)
    out_path = Path(output) if output else stamped(OUTPUT_XLSX)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Лист 1: Распределения
        dist_gen.to_excel(writer, sheet_name="Распределения")

        # Лист 2: Баланс пола
        gender.to_excel(writer, sheet_name="Баланс пола", index=False)

        # Лист 3: Инструкция по легенде
        legend = pd.DataFrame([
            {"Цвет": "Белый", "Значение": "0% (нет таких ответов)"},
            {"Цвет": "Голубой", "Значение": "~50% (среднее значение)"},
            {"Цвет": "Синий", "Значение": "Максимум (самый частый ответ)"},
            {"Примечание": "Цветовая шкала применена автоматически. "
                           "Вы можете изменить её через: Главная → Условное форматирование → Цветовые шкалы"}
        ])
        legend.to_excel(writer, sheet_name="Легенда", index=False)

        # Применяем авто-раскраску
        apply_conditional_formatting(writer, "Распределения", dist_gen)

    print(f"✅ Отчёт сохранён: {out_path}")
    print(f"   • Лист 'Распределения': {len(dist_gen)} вопросов")
    print(f"   • Лист 'Баланс пола': сравнение оригинала и генерации")
    print(f"   • Цветовая шкала применена автоматически")
    return out_path


if __name__ == "__main__":
    print("📊 Формирование отчёта...")
    build_report()