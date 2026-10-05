"""Отчёт сравнения трёх пресетов: Европа / Россия / Китай (2026).

Строится из qa.json + data/input/MEMpreset.json — по одному профилю на
культуру (индексы ответов из generate_data.COMPARISON_PRESETS). Вместо
отчёта с data bars генерируется аналитический Excel из четырёх листов:

1. «Тепловая карта» — все вопросы: Вопрос | Европеец | РФ | Китаец |
   Разница (Макс−Мин) | Тип вопроса | Блок | Категория. Ячейки залиты
   цветом по смыслу ответа (как условное форматирование «цветовые шкалы»),
   колонка «Разница» — настоящая цветовая шкала условного форматирования.
   Шапка с автофильтром выполняет роль срезов (Slicers): openpyxl не
   умеет настоящие срезы, поэтому фильтрация — через выпадающие списки.
2. «Радар по категориям» — средний балл категории для каждого пресета.
3. «Бабочка» — РФ вверх, Европа вниз от нуля: доля выбора второго варианта
   в парных вопросах по категориям.
4. «Инсайты» — топ-10 вопросов с максимальной разницей, звёзды, комментарий
   и горизонтальная сгруппированная диаграмма.
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, RadarChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill

import generate_data
from paths import COMPARE_XLSX, QA_JSON, stamped

# Порядок фиксирован: колонки отчёта идут в том же порядке
PRESETS = generate_data.COMPARISON_PRESETS
LABELS = ("Европеец", "РФ", "Китаец")

CATEGORIES = (
    "Автономия vs Зависимость",
    "Эмоциональная близость",
    "Быт и финансы",
    "Отношение к родственникам",
    "Коммуникация и секреты",
)

FILL_HEADER = PatternFill("solid", fgColor="D9D9D9")
FILL_LOW = PatternFill("solid", fgColor="F8696B")   # красный (цветовая шкала)
FILL_MID = PatternFill("solid", fgColor="FFEB84")   # жёлтый — нейтрально
FILL_HIGH = PatternFill("solid", fgColor="63BE7B")  # зелёный
FILL_FIRST = PatternFill("solid", fgColor="BDD7EE")  # синий — первый вариант пары
FILL_SECOND = PatternFill("solid", fgColor="F8CBAD") # оранжевый — второй вариант
FILL_NONE = PatternFill("solid", fgColor="E7E6E6")   # серый — без оценки

WRAP = Alignment(wrap_text=True, vertical="center")

# === Типы вопросов ===

YESNO_VALUES = {"да", "нет", "не знаю"}
DEMO_WORDS = ("ваш пол", "сколько вам лет", "семейный статус", "стаж брака",
              "у вас дети", "описываете ситуацию")


def classify_type(question, options) -> str:
    """Тип вопроса: Демография / Шкала Лайкерта / Да-Нет / Выбор пары / Прочее."""
    texts = [str(o).strip().casefold() for o in options if o is not None]
    if texts and all(t in YESNO_VALUES for t in texts):
        return "Да-Нет"
    question_cf = str(question).casefold()
    if question_cf.startswith("выберите утверждение"):
        return "Выбор пары"
    joined = " ".join(texts)
    if "согласен" in joined or "согласна" in joined:
        return "Шкала Лайкерта"
    if any(word in question_cf for word in DEMO_WORDS):
        return "Демография"
    return "Прочее"


# === Оценка ответа (0…1) ===

LIKERT_SCORES = {
    "совсем не согласен": 0.0,
    "скорее не согласен": 0.25,
    "скорее согласен": 0.6,
    "затрудняюсь ответить": 0.5,
    "затрудняюсь": 0.5,
    "полностью согласен": 1.0,
}
YESNO_SCORES = {"да": 1.0, "нет": 0.0, "не знаю": 0.5}


def score_answer(qtype: str, options, answer):
    """Балл ответа 0…1 или None (нет оценки).

    Шкала Лайкерта и Да-Нет — по тексту ответа (красный → зелёный).
    Выбор пары — позиция варианта: 0 = первый, 1 = второй (полярность,
    а не «хорошо/плохо»). Демография не оценивается.
    """
    if answer is None:
        return None
    text = str(answer).strip().casefold()
    if qtype == "Шкала Лайкерта":
        if text in LIKERT_SCORES:
            return LIKERT_SCORES[text]
        if "затрудн" in text:
            return 0.5
        if "соглас" in text:
            if "полностью" in text:
                return 1.0
            if "скорее" in text:
                return 0.25 if "не" in text else 0.6
            return 0.0 if "не" in text else 1.0
        return None
    if qtype == "Да-Нет":
        return YESNO_SCORES.get(text)
    if qtype == "Выбор пары":
        for index, option in enumerate(options):
            if option == answer or str(option) == str(answer):
                return index / (len(options) - 1) if len(options) > 2 else float(index)
        return None
    return None


def band(score) -> str | None:
    """Цветовая полоса: low=красный, mid=жёлтый, high=зелёный."""
    if score is None:
        return None
    if score < 0.42:
        return "low"
    if score <= 0.58:
        return "mid"
    return "high"


# === Категории и блоки ===

# Порядок важен: более специфичные правила раньше общих
_CATEGORY_RULES = (
    (("родител", "родственник", "тёща", "теща", "свекр", "свекрови",
      "мать", "отец", "свекров", "дочер"), "Отношение к родственникам"),
    (("деньг", "финан", "бюджет", "заработ", "расход", "покуп", "убор",
      "порядок", "хозяйств", "готов", "повар", "кулинар", "блюдо", "питани",
      "обед", "ужин", "магазин", "продукт", "еду", "еда", "стол", "быт",
      "домашн", "работ", "карьер", "ремонт", "дат", "поздравл", "подарок",
      "сюрприз", "телевиз", "спорт", "досуг", "увлеч", "отдых", "отпуск",
      "командировк"), "Быт и финансы"),
    (("зависе", "независи", "самостоятельн", "автоном", "ревн", "контрол",
      "свобод", "расстаться", "уйти от", "отдельн", "уедин", "личн",
      "одиночеств", "привычк", "свои интересы", "по-своему"),
     "Автономия vs Зависимость"),
    (("говор", "сказать", "рассказ", "обсужд", "поделиться", "объясн",
      "понима", "зна", "в курсе", "секрет", "высказ", "мнени", "призн",
      "откровен", "честн", "недоразум", "спор", "конфликт", "извин",
      "известност", "без слов", "мечта", "тема"), "Коммуникация и секреты"),
    (("близост", "сближа", "эмоци", "чувств", "любов", "привязан", "обид",
      "болезн", "плохо", "поддержк", "настроени", "восхищ", "горжусь",
      "уважа", "ценю", "нежно", "тепл", "счасть", "объят", "целу", "поцелу",
      "интим", "люблю", "грустно", "пережива", "душа", "обращаюсь",
      "впечатл", "раздраж"), "Эмоциональная близость"),
)

_DEFAULT_CATEGORY = {
    "Шкала Лайкерта": "Эмоциональная близость",
    "Выбор пары": "Эмоциональная близость",
    "Да-Нет": "Коммуникация и секреты",
    "Прочее": "Эмоциональная близость",
}


def category_of(question, options, qtype: str) -> str | None:
    """Смысловая категория для радара/инсайтов; у демографии — None."""
    if qtype == "Демография":
        return None
    text = (str(question) + " "
            + " ".join(str(o) for o in options if o is not None)).casefold()
    for words, name in _CATEGORY_RULES:
        if any(word in text for word in words):
            return name
    return _DEFAULT_CATEGORY.get(qtype)


def block_label(qtype: str, pos: int, n: int) -> str:
    """Структурный блок опросника (для колонки фильтрации «Блок»)."""
    if qtype == "Шкала Лайкерта":
        return "Шкалы привязанности"
    if qtype == "Выбор пары":
        return "Бинарный выбор"
    if qtype == "Да-Нет":
        if n == 181:
            return "Да/Нет: партнёр" if pos < 136 else "Да/Нет: супруга"
        return "Да/Нет"
    return qtype  # Демография / Прочее


# === Сбор строк отчёта ===

def build_rows(qa: dict, profiles: list[dict]) -> list[dict]:
    keys = list(qa)
    n = len(keys)
    rows = []
    for pos, key in enumerate(keys):
        options = qa[key]
        qtype = classify_type(key, options)
        answers = [profile[key] for profile in profiles]
        scores = [score_answer(qtype, options, answer) for answer in answers]
        valid = [s for s in scores if s is not None]
        diff = round(max(valid) - min(valid), 4) if len(valid) == len(PRESETS) else None
        rows.append({
            "question": key,
            "options": options,
            "qtype": qtype,
            "answers": answers,
            "scores": scores,
            "diff": diff,
            "block": block_label(qtype, pos, n),
            "category": category_of(key, options, qtype),
        })
    return rows


def answer_cell(row: dict, preset_index: int) -> tuple[str, PatternFill]:
    """Текст ячейки (эмодзи + ответ) и её заливка."""
    answer = row["answers"][preset_index]
    score = row["scores"][preset_index]
    shown = "—" if answer is None else str(answer)
    if score is None:
        return shown, FILL_NONE
    if row["qtype"] == "Выбор пары":
        second = score >= 0.5
        return ("🟠 " if second else "🔵 ") + shown, FILL_SECOND if second else FILL_FIRST
    tone = band(score)
    emoji = {"low": "🟥", "mid": "🟨", "high": "🟩"}[tone]
    fill = {"low": FILL_LOW, "mid": FILL_MID, "high": FILL_HIGH}[tone]
    return f"{emoji} {shown}", fill


# === Листы ===

def _header(ws, row: int, headers: list[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = Font(bold=True)
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)


def _sheet_heatmap(wb, rows: list[dict]) -> None:
    ws = wb.active
    ws.title = "Тепловая карта"
    ws["A1"] = "Сравнение пресетов 2026: Европа / Россия / Китай"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = ("🟥 «Совсем не согласен»/«Нет» · 🟨 нейтрально/«Затрудняюсь» · "
                "🟩 «Полностью согласен»/«Да» · 🔵 первый вариант пары · "
                "🟠 второй вариант · серый — без оценки (демография). "
                "Разница = макс.−мин. балл трёх пресетов (цветовая шкала). "
                "Фильтрация — выпадающие списки шапки: тип вопроса, блок, категория.")
    ws["A2"].font = Font(size=9, color="666666")

    _header(ws, 3, ["Вопрос", *LABELS, "Разница (Макс−Мин)",
                    "Тип вопроса", "Блок", "Категория"])
    current = 4
    for row in rows:
        ws.cell(row=current, column=1, value=row["question"]).alignment = WRAP
        for preset_index in range(len(PRESETS)):
            text, fill = answer_cell(row, preset_index)
            cell = ws.cell(row=current, column=2 + preset_index, value=text)
            cell.fill = fill
            cell.alignment = WRAP
        diff = ws.cell(row=current, column=5, value=row["diff"])
        diff.number_format = "0.00"
        diff.alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=current, column=6, value=row["qtype"])
        ws.cell(row=current, column=7, value=row["block"])
        ws.cell(row=current, column=8, value=row["category"] or "—")
        current += 1

    last = current - 1
    ws.freeze_panes = "A4"
    for column, width in (("A", 58), ("B", 30), ("C", 30), ("D", 30),
                          ("E", 14), ("F", 16), ("G", 22), ("H", 28)):
        ws.column_dimensions[column].width = width
    if last >= 4:
        ws.auto_filter.ref = f"A3:H{last}"
        # Настоящее условное форматирование «цветовая шкала»: чем больше
        # разница пресетов, тем краснее ячейка.
        ws.conditional_formatting.add(f"E4:E{last}", ColorScaleRule(
            start_type="num", start_value=0, start_color="63BE7B",
            mid_type="num", mid_value=0.5, mid_color="FFEB84",
            end_type="num", end_value=1, end_color="F8696B"))


def _sheet_radar(wb, rows: list[dict]) -> None:
    ws = wb.create_sheet("Радар по категориям")
    ws["A1"] = "Средний балл по категориям (шкала 0…1)"
    ws["A1"].font = Font(bold=True, size=13)
    _header(ws, 3, ["Категория", *LABELS])

    present = [c for c in CATEGORIES
               if any(r["category"] == c and any(s is not None for s in r["scores"])
                      for r in rows)]
    current = 4
    for category in present:
        ws.cell(row=current, column=1, value=category).alignment = WRAP
        for preset_index in range(len(PRESETS)):
            values = [r["scores"][preset_index] for r in rows
                      if r["category"] == category
                      and r["scores"][preset_index] is not None]
            mean = round(sum(values) / len(values), 3) if values else None
            cell = ws.cell(row=current, column=2 + preset_index, value=mean)
            cell.number_format = "0.00"
        current += 1

    ws.column_dimensions["A"].width = 32
    for column in ("B", "C", "D"):
        ws.column_dimensions[column].width = 14
    if present:
        chart = RadarChart()
        data = Reference(ws, min_col=2, max_col=1 + len(PRESETS),
                         min_row=3, max_row=3 + len(present))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=4,
                                       max_row=3 + len(present)))
        chart.title = "Профиль культуры: средние баллы категорий"
        chart.y_axis.scaling.min = 0
        chart.y_axis.scaling.max = 1
        chart.height, chart.width = 13, 20
        ws.add_chart(chart, "F3")


def _sheet_butterfly(wb, rows: list[dict]) -> None:
    """РФ вверх от нуля, Европа вниз: доля выбора второго варианта пары."""
    ws = wb.create_sheet("Бабочка")
    ws["A1"] = ("Бабочка: РФ vs Европа — доля выбора второго варианта "
                "в бинарных вопросах по категориям")
    ws["A1"].font = Font(bold=True, size=13)
    _header(ws, 3, ["Категория", "РФ", "Европа"])

    groups: dict[str, list[tuple[float, float]]] = {}
    eu_index, rf_index = 0, 1
    for row in rows:
        if row["qtype"] != "Выбор пары":
            continue
        eu, rf = row["scores"][eu_index], row["scores"][rf_index]
        if eu is None or rf is None or not row["category"]:
            continue
        groups.setdefault(row["category"], []).append((rf, eu))

    current = 4
    for category in [c for c in CATEGORIES if c in groups]:
        pairs = groups[category]
        rf_share = sum(p[0] for p in pairs) / len(pairs)
        eu_share = sum(p[1] for p in pairs) / len(pairs)
        ws.cell(row=current, column=1, value=category).alignment = WRAP
        up = ws.cell(row=current, column=2, value=round(rf_share, 3))
        down = ws.cell(row=current, column=3, value=round(-eu_share, 3))
        up.number_format = down.number_format = "0.00"
        current += 1

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 12
    made = current - 4
    if made:
        chart = BarChart()
        chart.type = "col"
        chart.grouping = "stacked"
        chart.overlap = 100
        data = Reference(ws, min_col=2, max_col=3, min_row=3, max_row=3 + made)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=4, max_row=3 + made))
        chart.title = "Согласие (вверх) vs особенность (вниз)"
        chart.y_axis.scaling.min = -1
        chart.y_axis.scaling.max = 1
        chart.height, chart.width = 11, 20
        ws.add_chart(chart, "F3")
    else:
        ws["A2"] = "Нет парных вопросов для сравнения"


COMMENT_BY_CATEGORY = {
    "Автономия vs Зависимость":
        "Западный профиль делает акцент на автономии и личных границах; "
        "для РФ и Китая естественнее взаимозависимость и участие семьи в решениях.",
    "Эмоциональная близость":
        "Европейская семья чаще проговаривает чувства словами; в РФ и Китае "
        "эмоциональная связь выражается через заботу и поступки.",
    "Быт и финансы":
        "Совместное хозяйство и общий бюджет — норма для РФ и Китая; "
        "в Европе чаще встречаются договорённости о раздельных расходах.",
    "Отношение к родственникам":
        "Коллективистские семьи (РФ, Китай) держат родственников ближе к решению "
        "пары; в Европе границы с родителями шире, вмешательство оценивается негативно.",
    "Коммуникация и секреты":
        "Открытость и прямой разговор о проблемах — европейская норма; "
        "в РФ и Китае чаще допускаются умолчания и негласное понимание «без слов».",
}
FALLBACK_COMMENT = ("Разница отражает разные культурные нормы: сравните ответы "
                    "трёх профилей и однородность цвета строки "
                    "на листе «Тепловая карта».")


def _sheet_insights(wb, rows: list[dict]) -> None:
    ws = wb.create_sheet("Инсайты топ-10")
    ws["A1"] = "Топ-10 противоречивых вопросов (макс. разница между пресетами)"
    ws["A1"].font = Font(bold=True, size=13)
    _header(ws, 3, ["№", "Вопрос", *LABELS, "Разница", "⭐", "Комментарий"])

    scored = sorted((r for r in rows if r["diff"] is not None),
                    key=lambda r: -r["diff"])
    top = scored[:10]
    current = 4
    for number, row in enumerate(top, start=1):
        stars = max(1, min(3, int(row["diff"] * 3 + 0.5)))
        comment = COMMENT_BY_CATEGORY.get(row["category"] or "", FALLBACK_COMMENT)
        ws.cell(row=current, column=1, value=number).alignment = Alignment(
            horizontal="center", vertical="center")
        ws.cell(row=current, column=2, value=row["question"]).alignment = WRAP
        for preset_index in range(len(PRESETS)):
            text, fill = answer_cell(row, preset_index)
            cell = ws.cell(row=current, column=3 + preset_index, value=text)
            cell.fill = fill
            cell.alignment = WRAP
        diff = ws.cell(row=current, column=6, value=row["diff"])
        diff.number_format = "0.00"
        diff.alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=current, column=7, value="⭐" * stars).alignment = \
            Alignment(horizontal="center", vertical="center")
        ws.cell(row=current, column=8, value=comment).alignment = WRAP
        ws.row_dimensions[current].height = 58
        current += 1

    for column, width in (("A", 5), ("B", 52), ("C", 26), ("D", 26), ("E", 26),
                          ("F", 10), ("G", 8), ("H", 58)):
        ws.column_dimensions[column].width = width
    if top:
        chart = BarChart()
        chart.type = "bar"          # горизонтальные столбцы
        chart.grouping = "clustered"
        data = Reference(ws, min_col=3, max_col=2 + len(PRESETS),
                         min_row=3, max_row=3 + len(top))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=2, min_row=4,
                                       max_row=3 + len(top)))
        chart.title = "Ответы трёх пресетов (балл 0…1)"
        chart.x_axis.scaling.min = 0
        chart.x_axis.scaling.max = 1
        chart.height, chart.width = 14, 24
        ws.add_chart(chart, "J3")


# === Публичное API ===

def build_report(output=None, qa_source=None, preset_source=None) -> Path:
    """Собирает Excel-отчёт сравнения пресетов и возвращает путь к файлу."""
    with open(Path(qa_source) if qa_source else QA_JSON, "r",
              encoding="utf-8") as f:
        qa = json.load(f)
    keys = list(qa)

    profiles = []
    for name in PRESETS:
        preset_key, indexes = generate_data._load_preset(name, keys,
                                                         preset_source)
        for pos, (key, options) in enumerate(qa.items()):
            if not 0 <= indexes[pos] < len(options):
                raise ValueError(
                    f"Набор «{preset_key}»: индекс {indexes[pos]} вне диапазона "
                    f"вариантов вопроса «{key}» (0…{len(options) - 1})")
        profiles.append({key: qa[key][indexes[pos]]
                         for pos, key in enumerate(qa)})

    rows = build_rows(qa, profiles)

    wb = Workbook()
    _sheet_heatmap(wb, rows)
    _sheet_radar(wb, rows)
    _sheet_butterfly(wb, rows)
    _sheet_insights(wb, rows)

    out = Path(output) if output else stamped(COMPARE_XLSX)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


if __name__ == "__main__":
    print(f"✅ Отчёт сравнения пресетов → {build_report()}")
