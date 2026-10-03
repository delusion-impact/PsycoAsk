"""Слой между HTTP-API и консольными скриптами.

Здесь нет копий логики пайплайна: функции из scripts/ вызываются напрямую
как обычные Python-функции. Скрипты импортируются лениво, чтобы окно
приложения открывалось мгновенно, а тяжёлые pandas/matplotlib грузились уже
при первом запуске задачи.
"""

from __future__ import annotations

import functools
import importlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app import config

Progress = Callable[[float, str], None]

# Рабочая папка выставляется в PSYCOASK_HOME до первого импорта paths:
# модуль читает переменную при загрузке и строит от неё все пути.
WORKSPACE: Path = config.setup_workspace()

_SCRIPTS_DIR = config.scripts_dir()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

STAMP_FILE = WORKSPACE / "data" / "intermediate" / "run_stamp.txt"


@functools.lru_cache(maxsize=None)
def module(name: str):
    """Импорт модуля из scripts/ с кэшированием."""
    return importlib.import_module(name)


def paths():
    return module("paths")


# === Штамп даты-времени ===

def begin_run() -> str:
    """Новый штамп для очередного прогона генерации.

    Штамп с точностью до секунды, а две задачи могут начаться в одну секунду:
    если файл с таким штампом уже есть, ждём следующей секунды, иначе второй
    прогон затрёт первый.
    """
    deadline = time.monotonic() + 3.0
    while True:
        stamp = datetime.now().strftime(paths().STAMP_FORMAT)
        taken = data_dir("generated") / f"generated_survey_{stamp}.xlsx"
        if not taken.exists() or time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    os.environ[paths().STAMP_ENV] = stamp
    STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(stamp, encoding="utf-8")
    return stamp


def current_stamp() -> str:
    """Штамп текущего прогона.

    Графики и отчёты берут тот же штамп, что и сгенерированный файл, иначе
    после перезапуска приложения результаты одного прогона разъедутся.
    """
    if STAMP_FILE.exists():
        stamp = STAMP_FILE.read_text(encoding="utf-8").strip()
        if stamp:
            os.environ[paths().STAMP_ENV] = stamp
            return stamp
    return begin_run()


# === Файлы выгрузок ===

def _noop(_fraction: float, _message: str) -> None:
    return None


def data_dir(name: str) -> Path:
    return WORKSPACE / "data" / name


def safe_name(filename: str) -> str:
    """Имя файла без путей и опасных символов."""
    name = Path(str(filename or "").replace("\\", "/")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "upload.xlsx"


def list_inputs() -> list[dict[str, Any]]:
    """Excel-файлы, доступные для обработки."""
    folder = data_dir("input")
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in EXCEL_SUFFIXES:
            continue
        if path.name.startswith("~$"):  # временный файл открытого Excel
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return items


def store_upload(filename: str, data: bytes) -> Path:
    """Кладёт загруженную выгрузку в data/input."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
    folder = data_dir("input")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name(filename)
    if path.suffix.lower() not in EXCEL_SUFFIXES:
        path = path.with_suffix(".xlsx")
    path.write_bytes(data)
    return path


def resolve_input(name: str) -> Path:
    """Путь к выгрузке по имени; имя не должно выходить из data/input."""
    path = (data_dir("input") / safe_name(name)).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден в data/input: {name}")
    return path


# === Шаги пайплайна ===

def parse_input(filename: str, progress: Progress = _noop) -> dict[str, Any]:
    """Шаг 1: Excel → survey_data.json + qa.json."""
    source = resolve_input(filename)
    core = paths()
    core.ensure_dirs()

    progress(0.15, f"Читаем {source.name}")
    records = module("xlsx_to_json").parse_xlsx_to_json(source, core.SURVEY_JSON)

    progress(0.65, "Собираем словарь вопросов и ответов")
    qa = module("prepare_qa").prepare_qa(core.SURVEY_JSON, core.QA_JSON)

    progress(1.0, "Парсинг завершён")
    answers = sum(len(options) for options in qa.values())
    return {
        "file": source.name,
        "records": len(records),
        "questions": len(qa),
        "answers": answers,
        "sample": list(qa)[:5],
    }


def generate(count: int, progress: Progress = _noop) -> dict[str, Any]:
    """Шаг 2: qa.json → generated_data.json + generated_survey_<stamp>.xlsx."""
    core = paths()
    core.ensure_dirs()
    if not Path(core.QA_JSON).exists():
        raise FileNotFoundError("Сначала выполните парсинг выгрузки")

    stamp = begin_run()

    progress(0.1, f"Генерируем {count} анкет")
    module("generate_data").generate_and_save(count, qa_source=core.QA_JSON,
                                              output=core.GENERATED_JSON)

    progress(0.7, "Выгружаем Excel")
    xlsx = module("json_to_xlsx").convert(core.GENERATED_JSON,
                                          core.stamped(core.GENERATED_XLSX))

    progress(1.0, "Генерация завершена")
    return {
        "count": count,
        "stamp": stamp,
        "xlsx": config.relative(xlsx),
    }


def build_charts(progress: Progress = _noop) -> list[Path]:
    """Шаг 3: графики PNG."""
    core = paths()
    core.ensure_dirs()
    if not Path(core.GENERATED_JSON).exists():
        raise FileNotFoundError("Сначала выполните генерацию анкет")

    current_stamp()
    files: list[Path] = []

    # Прогресс делится по графикам, а не по этапам: иначе полоса висит на
    # одной цифре все время, пока matplotlib рисует листы.
    figures = [("Тепловая карта ответов", lambda: module("visualize_answers")
                .build_heatmap(core.GENERATED_JSON, show=False))]

    if Path(core.SURVEY_JSON).exists():
        comparison = module("visualize_comparison")
        orig, gen = comparison.load_data(core.SURVEY_JSON, core.GENERATED_JSON)
        figures += [
            ("Баланс пола: оригинал против генерации",
             lambda: comparison.plot_gender_balance(orig, gen, show=False)),
            ("Распределения топ-10 вопросов",
             lambda: comparison.plot_distributions_comparison(orig, gen, show=False)),
            ("Корреляция шкалы Лайкерта — оригинал",
             lambda: comparison.plot_likert_heatmap(orig, "original", " — Оригинал", show=False)),
            ("Корреляция шкалы Лайкерта — генерация",
             lambda: comparison.plot_likert_heatmap(gen, "generated", " — Генерация", show=False)),
        ]

    for index, (title, build) in enumerate(figures):
        progress(index / len(figures), title)
        produced = build()
        if produced:
            files.append(Path(produced))

    progress(1.0, "Графики готовы")
    return files


def build_reports(progress: Progress = _noop) -> list[Path]:
    """Шаг 4: отчёты Excel."""
    core = paths()
    core.ensure_dirs()
    if not Path(core.GENERATED_JSON).exists():
        raise FileNotFoundError("Сначала выполните генерацию анкет")

    current_stamp()
    files: list[Path] = []

    progress(0.2, "Отчёт с распределениями")
    files.append(module("visualize_to_excel").build_report(core.GENERATED_JSON,
                                                           core.SURVEY_JSON))

    progress(0.7, "Отчёт с гистограммами в ячейках")
    files.append(module("visualize_to_excel_bars").build_bars_report(core.GENERATED_JSON))

    progress(1.0, "Отчёты готовы")
    return files


# === Артефакты и предпросмотр ===

STAMP_PATTERN = re.compile(r"\d{8}-\d{6}")


def _describe(path: Path) -> dict[str, Any]:
    stat = path.stat()
    # Категория нужна интерфейсу, чтобы показывать результаты генерации и
    # визуализации по отдельности: анкеты лежат в data/generated/, графики и
    # отчёты — в output/.
    parent = path.parent.name.lower()
    category = "generate" if parent == "generated" else "visualize"
    return {
        "name": path.name,
        "path": config.relative(path),
        "kind": path.suffix.lower().lstrip("."),
        "category": category,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def _result_files() -> list[Path]:
    """Все файлы-результаты: анкеты, графики и отчёты."""
    folders = (
        (data_dir("generated"), "generated_survey_*.xlsx"),
        (WORKSPACE / "output" / "charts", "*.png"),
        (WORKSPACE / "output" / "reports", "*_*.xlsx"),
    )
    files: list[Path] = []
    for folder, pattern in folders:
        if folder.exists():
            files += sorted(folder.glob(pattern))
    return files


def artifacts(stamp: str | None = None) -> list[dict[str, Any]]:
    """Файлы последнего прогона — с одним штампом в имени.

    Штамп ищется в самих файлах, а не берётся из состояния приложения: тогда
    результаты, сделанные консольным пайплайном, тоже видны в интерфейсе.
    """
    files = _result_files()
    stamps = {match.group(0) for path in files
              if (match := STAMP_PATTERN.search(path.stem))}
    current = stamp or (max(stamps) if stamps else None)
    if current:
        files = [path for path in files if current in path.stem]
    return [_describe(path) for path in sorted(files, key=lambda item: item.name)]


def latest_stamp() -> str | None:
    """Штамп последнего прогона по уже созданным файлам."""
    stamps = {match.group(0) for path in _result_files()
              if (match := STAMP_PATTERN.search(path.stem))}
    return max(stamps) if stamps else None


def resolve_in_workspace(relative_path: str) -> Path:
    """Путь по относительному пути; наружу рабочей папки выйти нельзя.

    Принимается и файл, и папка: /api/open открывает в Проводнике и то, и
    другое (файл — с выделением, папку — целиком).
    """
    workspace = WORKSPACE.resolve()
    path = (workspace / str(relative_path).replace("\\", "/")).resolve()
    if path != workspace and workspace not in path.parents:
        raise PermissionError("Путь за пределами рабочей папки")
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {relative_path}")
    return path


def state() -> dict[str, Any]:
    """Состояние, из которого мастер рисует текущий шаг."""
    core = paths()
    core.ensure_dirs()

    inputs = list_inputs()
    survey = Path(core.SURVEY_JSON)
    qa = Path(core.QA_JSON)
    generated = Path(core.GENERATED_JSON)

    info: dict[str, Any] = {
        "workspace": str(WORKSPACE),
        "inputs": inputs,
        "parsed": False,
        "generated": False,
        "stamp": None,
        "artifacts": [],
    }

    if qa.exists():
        try:
            qa_map = json.loads(qa.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            qa_map = {}
        options = sum(len(values) for values in qa_map.values())
        records = len(json.loads(generated.read_text(encoding="utf-8"))) if generated.exists() else 0
        info.update({
            "parsed": bool(qa_map),
            "questions": len(qa_map),
            "answers": options,
            "survey_exists": survey.exists(),
            "generated": records > 0,
            "generated_records": records,
            "question_preview": [
                {"question": name, "options": [str(value) for value in values[:6]]}
                for name, values in list(qa_map.items())[:8]
            ],
        })
        if info["generated"]:
            info["stamp"] = latest_stamp() or current_stamp()
            info["artifacts"] = artifacts(info["stamp"])
    return info