"""Интерактивный запуск всего пайплайна.

    python scripts/run_pipeline.py            # шаг за шагом, без окон графиков
    python scripts/run_pipeline.py --show     # показывать окна matplotlib
    python scripts/run_pipeline.py --yes      # без вопросов: все шаги по умолчанию

Шаги:
    1. Парсинг выгрузки из data/input → survey_data.json + qa.json      (обязательный)
    2. Генерация синтетических ответов → generated_data.json
       и выгрузка в Excel               → generated_survey_*.xlsx       (обязательный)
    3. Визуализация PNG                 → output/charts/*.png           (можно пропустить)
    4. Визуализация Excel                → output/reports/*.xlsx         (можно пропустить)

Вопрос про каждый шаг задаётся только после того, как предыдущий шаг реально
создал свой файл. Ответы вводятся цифрами, Enter — вариант по умолчанию.
Имена всех файлов-результатов получают штамп даты-времени, поэтому прогоны
не затирают друг друга.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from generate_data import MAX_NUM_RECORDS, NUM_RECORDS as DEFAULT_NUM_RECORDS
from paths import (
    CHARTS_DIR,
    GENERATED_JSON,
    GENERATED_XLSX,
    INPUT_DIR,
    QA_JSON,
    REPORTS_DIR,
    STAMP_ENV,
    STAMP_FORMAT,
    SURVEY_JSON,
    ensure_dirs,
    run_stamp,
    stamped,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent

AUTO_YES = "--yes" in sys.argv[1:]
SHOW_PLOTS = "--show" in sys.argv[1:]

DONE = "выполнен"
SKIPPED = "пропущен"
STOPPED = "остановлен"
CANCELLED = "отменён"

MARK_DONE = "✅"
MARK_SKIPPED = "⏭ "
MARK_STOPPED = "⏹ "
MARK_CANCELLED = "🚫"

REQUIRED_PACKAGES = ("numpy", "pandas", "openpyxl", "matplotlib", "seaborn")

# Действия, возвращаемые вопросами
YES = "yes"
NO = "no"
SKIP = "skip"
CANCEL = "cancel"


# === Вопросы пользователю ===

@dataclass(frozen=True)
class Choice:
    label: str
    action: str


def ask(question: str, choices: tuple[Choice, ...], default: str) -> str:
    """Задаёт вопрос с пронумерованными вариантами и возвращает действие.

    Ввод — цифра от 1 до количества вариантов, Enter — вариант по умолчанию.
    """
    if AUTO_YES:
        return default
    default_label = next(c.label for c in choices if c.action == default)

    print()
    print(question)
    for index, choice in enumerate(choices, start=1):
        print(f"    [{index}] {choice.label}")
    print(f"    (Enter → {default_label})")
    print(f"    Ответ: цифра 1…{len(choices)} или Enter")

    while True:
        try:
            raw = input("    > ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1].action
        print(f"    ⚠️  Введите номер от 1 до {len(choices)} или нажмите Enter.")


def ask_count(question: str, default: int, limit: int = MAX_NUM_RECORDS) -> int | None:
    """Запрашивает количество записей. None — пользователь отменил шаг (ввод 0)."""
    if AUTO_YES:
        return default
    print()
    print(question)
    print(f"    (Enter → {default}, 0 → отмена, максимум {limit})")
    print(f"    Ответ: число или Enter")

    while True:
        try:
            raw = input("    > ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        if raw.isdigit():
            value = int(raw)
            if value == 0:
                return None
            if 1 <= value <= limit:
                return value
            print(f"    ⚠️  Нужно число от 1 до {limit}.")
            continue
        print(f"    ⚠️  Введите число от 1 до {limit}, 0 или нажмите Enter.")


# === Проверка окружения ===

def preflight() -> bool:
    """Проверяет, что пакеты из requirements.txt доступны текущему интерпретатору.

    Самая частая поломка — venv, собранный под одну версию Python, а пакеты
    установлены из колёс под другую; тогда любой шаг падает на импорте numpy.
    """
    broken: list[str] = []
    for name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            broken.append(name if isinstance(exc, ModuleNotFoundError)
                          and exc.name == name else f"{name} ({exc})")

    if not broken:
        return True

    print("❌ Окружение не готово к запуску.")
    print(f"   Интерпретатор: {sys.executable}")
    print(f"   Python {sys.version.split()[0]}, платформа {sys.platform}")
    print(f"   Не импортируются: {', '.join(broken)}")
    print()
    print("   Обычно это значит, что пакеты установлены не под тот Python,")
    print("   которым создан .venv. Переустановите их:")
    print()
    print("       python -m pip install --force-reinstall --no-cache-dir -r requirements.txt")
    print()
    print("   Если не помогло — пересоздайте окружение:")
    print()
    print("       rmdir /s /q .venv")
    print("       py -3.14 -m venv .venv")
    print("       .venv\\Scripts\\activate")
    print("       pip install -r requirements.txt")
    return False


# === Запуск отдельных скриптов ===

def rel(path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONWARNINGS", None)
    if not SHOW_PLOTS:
        env["MPLBACKEND"] = "Agg"
    return env


def child_flags() -> list[str]:
    """Без окон графиков plt.show() ругается предупреждением — глушим именно его."""
    if SHOW_PLOTS:
        return []
    return ["-W", "ignore:FigureCanvasAgg is non-interactive:UserWarning"]


def run_script(script: str, *args: str) -> bool:
    """Запускает scripts/<script> и возвращает True при успешном коде выхода."""
    command = [sys.executable, *child_flags(), str(SCRIPTS_DIR / script), *args]
    print(f"    $ python scripts/{script} {' '.join(args)}".rstrip())
    sys.stdout.flush()  # иначе вывод родителя перемешается с выводом скрипта
    completed = subprocess.run(command, cwd=ROOT_DIR, env=child_env())
    if completed.returncode != 0:
        print(f"    ❌ {script} завершился с кодом {completed.returncode}")
        return False
    return True


def missing(*paths) -> bool:
    absent = [rel(p) for p in paths if not Path(p).exists()]
    if not absent:
        return False
    print(f"    ❌ Не найдено: {', '.join(absent)}")
    print("       Это обязательный шаг — вернитесь назад или выполните его вручную.")
    return True


def found_any(folder: Path, pattern: str) -> bool:
    return any(Path(folder).glob(pattern))


# === Шаги ===

def find_input_file() -> Path | None:
    """Ищет Excel-выгрузку в data/input (при нескольких — спрашивает)."""
    files = sorted(
        path for path in INPUT_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}
        and not path.name.startswith("~$")
    )
    if not files:
        return None
    if len(files) == 1:
        return files[0]

    print(f"    Найдено файлов в {rel(INPUT_DIR)}: {len(files)}")
    choices = tuple(
        Choice(path.name, f"file:{index}")
        for index, path in enumerate(files, start=1)
    )
    action = ask("Какую выгрузку обрабатывать?", choices + (Choice("отмена", CANCEL),),
                 f"file:1")
    if action == CANCEL:
        return None
    return files[int(action.split(":", 1)[1]) - 1]


def step_parse() -> str:
    """data/input/*.xlsx → survey_data.json + qa.json. Пропустить нельзя."""
    source = find_input_file()
    if source is None:
        print(f"    ❌ В папке {rel(INPUT_DIR)} нет Excel-файлов")
        return CANCELLED

    size_kb = source.stat().st_size / 1024
    action = ask(
        f"Обнаружена выгрузка «{source.name}» ({size_kb:.0f} КБ). Обработать её?",
        (Choice("да", YES), Choice("нет", NO)),
        YES,
    )
    if action == NO:
        print("    ⏹  Парсинг не выполнен — шаг обязательный, пайплайн останавливается")
        return STOPPED

    if not run_script("xlsx_to_json.py", rel(source)):
        return CANCELLED
    if not run_script("prepare_qa.py"):
        return CANCELLED
    if missing(QA_JSON):
        return CANCELLED
    return DONE


def step_generate() -> str:
    """qa.json → generated_data.json + generated_survey_<stamp>.xlsx. Пропустить нельзя."""
    if missing(QA_JSON):
        return CANCELLED

    count = ask_count("Сколько анкет сгенерировать?", DEFAULT_NUM_RECORDS)
    if count is None:
        return CANCELLED
    print(f"    Будет сгенерировано записей: {count}")

    if not run_script("generate_data.py", str(count)):
        return CANCELLED
    if missing(GENERATED_JSON):
        return CANCELLED
    if not run_script("json_to_xlsx.py"):
        return CANCELLED
    if missing(stamped(GENERATED_XLSX)):
        return CANCELLED
    return DONE


def step_charts() -> str:
    """generated_data.json → output/charts/*_<stamp>.png"""
    if missing(GENERATED_JSON):
        return SKIPPED

    action = ask("Построить графики (PNG)?",
                 (Choice("да", YES), Choice("пропустить", SKIP), Choice("отмена", CANCEL)),
                 YES)
    if action == SKIP:
        print(f"    {MARK_SKIPPED} Графики пропущены")
        return SKIPPED
    if action == CANCEL:
        return CANCELLED

    if not run_script("visualize_answers.py"):
        return CANCELLED
    if Path(SURVEY_JSON).exists():
        if not run_script("visualize_comparison.py"):
            return CANCELLED
    else:
        print(f"    ⚠️  {rel(SURVEY_JSON)} нет — сравнение с оригиналом пропущено")
    if not found_any(CHARTS_DIR, "answer_heatmap_*.png"):
        print("    ❌ График answer_heatmap не создан")
        return CANCELLED
    return DONE


def step_reports() -> str:
    """generated_data.json → output/reports/*_<stamp>.xlsx"""
    if missing(GENERATED_JSON):
        return SKIPPED

    action = ask("Собрать отчёты в Excel?",
                 (Choice("да", YES), Choice("пропустить", SKIP), Choice("отмена", CANCEL)),
                 YES)
    if action == SKIP:
        print(f"    {MARK_SKIPPED} Excel-отчёты пропущены")
        return SKIPPED
    if action == CANCEL:
        return CANCELLED

    if not run_script("visualize_to_excel.py"):
        return CANCELLED
    if not run_script("visualize_to_excel_bars.py"):
        return CANCELLED
    if not found_any(REPORTS_DIR, "visualization_report_*.xlsx"):
        print("    ❌ Отчёт visualization_report не создан")
        return CANCELLED
    return DONE


@dataclass(frozen=True)
class Step:
    number: int
    title: str
    required: bool
    run: Callable[[], str]
    artifacts: tuple[Path, ...] = ()
    artifact_glob: str = ""


def build_steps() -> list[Step]:
    return [
        Step(1, "Парсинг выгрузки и словарь вопросов", True, step_parse,
             (SURVEY_JSON, QA_JSON)),
        Step(2, "Генерация синтетических ответов и выгрузка в Excel", True, step_generate,
             (GENERATED_JSON, stamped(GENERATED_XLSX))),
        Step(3, "Визуализация: графики PNG", False, step_charts,
             (CHARTS_DIR,), f"*_{run_stamp()}.png"),
        Step(4, "Визуализация: отчёты Excel", False, step_reports,
             (REPORTS_DIR,), f"*_{run_stamp()}.xlsx"),
    ]


def print_header(step: Step, total: int) -> None:
    flag = "обязательный" if step.required else "можно пропустить"
    print()
    print("─" * 72)
    print(f"  Шаг {step.number}/{total}. {step.title}  ({flag})")
    print("─" * 72)


def print_summary(results: list[tuple[Step, str]]) -> None:
    print()
    print("─" * 72)
    print("  Итог")
    print("─" * 72)
    marks = {DONE: MARK_DONE, SKIPPED: MARK_SKIPPED,
             STOPPED: MARK_STOPPED, CANCELLED: MARK_CANCELLED}
    for step, status in results:
        print(f"  {marks[status]} {step.title} — {status}")

    if any(status in (CANCELLED, STOPPED) for _, status in results):
        print()
        print("  Пайплайн остановлен.")
        return

    # Показываем только то, что действительно создано в этом запуске
    produced: list[str] = []
    for step, status in results:
        if status != DONE:
            continue
        plain = step.artifacts[:-1] if step.artifact_glob else step.artifacts
        produced += [rel(path) for path in plain if Path(path).exists()]
        if step.artifact_glob:
            folder = rel(step.artifacts[0]).replace("\\", "/")
            if found_any(step.artifacts[0], step.artifact_glob):
                produced.append(f"{folder}/{step.artifact_glob}")

    if produced:
        print()
        print("  Создано в этом запуске:")
        for item in produced:
            print(f"    • {item}")


def main() -> int:
    ensure_dirs()
    if not preflight():
        return 1

    # Один штамп на весь прогон: результаты разных шагов не разъедутся по меткам
    os.environ[STAMP_ENV] = datetime.now().strftime(STAMP_FORMAT)

    steps = build_steps()
    if AUTO_YES:
        print("🤖 Автоматический режим: выполняются все шаги без вопросов.")
    print(f"🕒 Прогон {os.environ[STAMP_ENV]} — файлы результатов получат такой штамп")

    results: list[tuple[Step, str]] = []
    for step in steps:
        print_header(step, len(steps))
        try:
            status = step.run()
        except KeyboardInterrupt:
            print()
            print(f"{MARK_CANCELLED} Прервано пользователем (Ctrl+C)")
            return 130
        results.append((step, status))
        if status in (CANCELLED, STOPPED):
            print_summary(results)
            return 0

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())