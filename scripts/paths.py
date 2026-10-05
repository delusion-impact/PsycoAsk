import os
from datetime import datetime
from pathlib import Path

# Корень рабочего пространства. По умолчанию — папка проекта, но её можно
# переопределить переменной окружения PSYCOASK_HOME: гибридному приложению
# (EXE) нужна папка, доступная для записи, а распакованная сборка лежит в
# Program Files и писать туда нельзя.
HOME_ENV = "PSYCOASK_HOME"

_project_root = Path(__file__).resolve().parent.parent
ROOT_DIR = Path(os.environ[HOME_ENV]).resolve() if os.environ.get(HOME_ENV) else _project_root

DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
GENERATED_DATA_DIR = DATA_DIR / "generated"

OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"

SURVEY_JSON = INTERMEDIATE_DIR / "survey_data.json"
QA_JSON = INTERMEDIATE_DIR / "qa.json"
GENERATED_JSON = GENERATED_DATA_DIR / "generated_data.json"
GENERATED_XLSX = GENERATED_DATA_DIR / "generated_survey.xlsx"

REPORT_XLSX = REPORTS_DIR / "visualization_report.xlsx"
BARS_XLSX = REPORTS_DIR / "visualization_bars.xlsx"
# Отчёт сравнения трёх пресетов (тепловая карта, радар, бабочка, инсайты)
COMPARE_XLSX = GENERATED_DATA_DIR / "generated_compare.xlsx"

# Профили респондентов для генерации (опции на шаге «2 Генерация»)
MEM_PRESET_JSON = INPUT_DIR / "MEMpreset.json"

ALL_DIRS = (
    INPUT_DIR,
    INTERMEDIATE_DIR,
    GENERATED_DATA_DIR,
    REPORTS_DIR,
)


def ensure_dirs():
    for directory in ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


STAMP_ENV = "PSYCOASK_STAMP"
STAMP_FORMAT = "%Y%m%d-%H%M%S"


def run_stamp() -> str:
    """Штамп даты-времени для имён результатов, например 20261003-150112.

    Внутри одного запуска run_pipeline.py штамп один на весь пайплайн, иначе
    шаги, стартовавшие в разные секунды, разошлись бы по разным меткам.
    """
    return os.environ.get(STAMP_ENV) or datetime.now().strftime(STAMP_FORMAT)


def stamped(path) -> Path:
    """Добавляет к имени файла результата штамп: report.xlsx → report_20261003-150112.xlsx"""
    path = Path(path)
    return path.with_name(f"{path.stem}_{run_stamp()}{path.suffix}")