"""Слой между HTTP-API и консольными скриптами.

Здесь нет копий логики пайплайна: функции из scripts/ вызываются напрямую
как обычные Python-функции. Скрипты импортируются лениво, чтобы окно
приложения открывалось мгновенно, а тяжёлые pandas/openpyxl грузились уже
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

EXCEL_SUFFIXES = {".txt", ".xlsx", ".xls", ".xlsm"}  # основной источник — .txt
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
        taken = any(
            folder.exists() and any(stamp in path.stem for path in folder.iterdir())
            for folder in (data_dir("generated"), WORKSPACE / "output" / "reports")
        )
        if not taken or time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    os.environ[paths().STAMP_ENV] = stamp
    STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(stamp, encoding="utf-8")
    return stamp


def current_stamp() -> str:
    """Штамп текущего прогона.

    Отчёты берут тот же штамп, что и сгенерированный файл, иначе
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
    """Файлы-результаты, доступные для выборки: txt/xlsx из data/input."""
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
        path = path.with_suffix(".txt")
    # Не затираем существующую выгрузку: добавляем числовой суффикс
    base, suffix = path.stem, path.suffix
    counter = 1
    while path.exists():
        path = path.with_name(f"{base} ({counter}){suffix}")
        counter += 1
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
    """Шаг 1: текстовый источник (data/input/*.txt) → qa.json."""
    source = resolve_input(filename)
    if source.suffix.lower() != ".txt":
        raise ValueError(f"Ожидается текстовый файл .txt, получен: {source.name}")
    core = paths()
    core.ensure_dirs()

    progress(0.15, f"Читаем {source.name}")
    qa = module("txt_to_qa").import_qa(source, core.QA_JSON)

    progress(1.0, "Импорт завершён")
    answers = sum(len(options) for options in qa.values())
    return {
        "file": source.name,
        "questions": len(qa),
        "answers": answers,
        "sample": list(qa)[:5],
    }


def generate(count: int, progress: Progress = _noop, bars: bool = False,
             preset: str | None = None, compare: bool = False) -> dict[str, Any]:
    """Шаг 2: qa.json → generated_data.json + generated_survey_<stamp>.xlsx

    compare=True — режим «Сравнение»: по анкете на каждый пресет (3 шт.)
    и вместо data bars собирается отчёт generated_compare_<stamp>.xlsx
    (тепловая карта, радар, бабочка, инсайты). preset/bars в этом режиме
    не используются.
    preset — профиль респондента из MEMpreset.json; None — случайные ответы."""
    core = paths()
    core.ensure_dirs()
    if not Path(core.QA_JSON).exists():
        raise FileNotFoundError("Сначала выполните парсинг выгрузки")

    stamp = begin_run()

    if compare:
        count = len(module("generate_data").COMPARISON_PRESETS)
        progress(0.1, "Генерируем 3 анкеты: Европа / РФ / Китай")
    else:
        progress(0.1, f"Генерируем {count} анкет"
                 + (f" (набор «{preset}»)" if preset else ""))
    module("generate_data").generate_and_save(count, qa_source=core.QA_JSON,
                                              output=core.GENERATED_JSON,
                                              preset=preset, compare=compare)

    progress(0.7, "Выгружаем Excel")
    xlsx = module("json_to_xlsx").convert(core.GENERATED_JSON,
                                          core.stamped(core.GENERATED_XLSX))

    report_xlsx = None
    bars_xlsx = None
    if compare:
        progress(0.85, "Собираем отчёт сравнения: тепловая карта и графики")
        report_xlsx = module("compare_presets").build_report(
            output=xlsx.with_name(f"generated_compare_{stamp}{xlsx.suffix}"))
    elif bars:
        progress(0.85, "Собираем отчёт Excel с Data Bars")
        bars_target = xlsx.with_name(f"generated_bars_{stamp}{xlsx.suffix}")
        bars_xlsx = module("visualize_to_excel_bars").build_bars_report(
            core.GENERATED_JSON, output=bars_target)

    progress(1.0, "Генерация завершена")
    result = {
        "count": count,
        "stamp": stamp,
        "xlsx": config.relative(xlsx),
        "preset": preset,
        "compare": compare,
    }
    if report_xlsx is not None:
        result["report"] = config.relative(report_xlsx)
    if bars_xlsx is not None:
        result["bars"] = config.relative(bars_xlsx)
    return result


# === Артефакты и предпросмотр ===

STAMP_PATTERN = re.compile(r"\d{8}-\d{6}")


def _describe(path: Path) -> dict[str, Any]:
    stat = path.stat()
    # Категория нужна интерфейсу, чтобы показывать результаты генерации и
    # отчёты по отдельности: анкеты лежат в data/generated/, отчёты — в
    # output/reports/.
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
    """Все файлы-результаты: анкеты и отчёты."""
    folders = (
        (data_dir("generated"), "generated_*.xlsx"),
        (WORKSPACE / "output" / "reports", "*_*.xlsx"),
    )
    files: list[Path] = []
    for folder, pattern in folders:
        if folder.exists():
            files += sorted(folder.glob(pattern))
    return files


def _stamp_of(path: Path) -> str | None:
    match = STAMP_PATTERN.search(path.stem)
    return match.group(0) if match else None


def artifacts(stamp: str | None = None) -> list[dict[str, Any]]:
    """Файлы последнего прогона — с одним штампом в имени.

    Штамп ищется в самих файлах, а не берётся из состояния приложения: тогда
    результаты, сделанные консольным пайплайном, тоже видны в интерфейсе.
    """
    files = _result_files()
    stamps = {stamped for path in files if (stamped := _stamp_of(path))}
    current = stamp or (max(stamps) if stamps else None)
    if current:
        files = [path for path in files if _stamp_of(path) == current]
    return [_describe(path) for path in sorted(files, key=lambda item: item.name)]


def latest_stamp() -> str | None:
    """Штамп последнего прогона по уже созданным файлам."""
    stamps = {stamped for path in _result_files() if (stamped := _stamp_of(path))}
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


_GENERATED_CACHE: dict[str, Any] = {"key": None, "count": 0}


def _generated_records() -> int:
    """Число записей в generated_data.json с кэшем по mtime+size.

    state() опрашивается каждые 300 мс во время задач — перечитывать и
    перепарсивать весь JSON на каждый опрос не стоит.
    """
    core = paths()
    path = Path(core.GENERATED_JSON)
    try:
        stat = path.stat()
    except OSError:
        return 0
    key = (path, stat.st_mtime_ns, stat.st_size)
    if _GENERATED_CACHE["key"] == key:
        return _GENERATED_CACHE["count"]
    try:
        count = len(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        count = 0
    _GENERATED_CACHE["key"] = key
    _GENERATED_CACHE["count"] = count
    return count


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
        records = _generated_records() if generated.exists() else 0
        info.update({
            "parsed": bool(qa_map),
            "questions": len(qa_map),
            "answers": options,
            "survey_exists": survey.exists(),
            "generated": records > 0,
            "generated_records": records,
            "max_count": module("generate_data").MAX_NUM_RECORDS,
        })
        if info["generated"]:
            # Только читаем штамп из файлов: state() — GET, и не должен
            # создавать run_stamp.txt или заводить новый прогон.
            info["stamp"] = latest_stamp()
            info["artifacts"] = artifacts(info["stamp"])
    return info