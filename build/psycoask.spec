# -*- mode: python ; coding: utf-8 -*-
"""Сборка PsycoAsk в один EXE (PyInstaller).

    .venv\\Scripts\\pyinstaller build\\psycoask.spec --noconfirm

Один файл: dist\\PsycoAsk-<версия>.exe переносится куда угодно и запускается
без каталогов рядом. При запуске он распаковывается во временную папку, поэтому
первый старт занимает несколько секунд — это цена автономности.
За сборку каталогом (быстрый старт) есть build\\build.ps1 -AsFolder.

Особенность: скрипты пайплайна из scripts/ грузятся в приложении через
importlib по имени файла. PyInstaller такие импорты не видит, поэтому они
перечислены в hiddenimports — иначе в сборку не попадут ни сами скрипты,
ни их зависимости (pandas, openpyxl).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

# Версию читаем из исходника, не импортируя app: импорт трогает stdout
# и окружение, а это ломает вывод PyInstaller при анализе.
import re as _re

APP_NAME = "PsycoAsk"
_init_text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
APP_VERSION = _re.search(r'APP_VERSION = "([^"]+)"', _init_text).group(1)

FRONTEND = ROOT / "frontend"
SCRIPTS = ROOT / "scripts"
ICON = ROOT / "assets" / "icon.ico"

PIPELINE_MODULES = [
    "paths",
    "txt_to_qa",
    "xlsx_to_json",
    "prepare_qa",
    "generate_data",
    "json_to_xlsx",
    "visualize_to_excel",
    "visualize_to_excel_bars",
    "compare_presets",
]

# openpyxl/pandas хранят данные (шаблоны, стили), которые нужны в готовом виде:
# коллектор копирует их рядом с библиотеками. data/input/MEMpreset.json —
# наборы ответов для шага 2: из EXE их читает generate_data.
datas = [
    (str(FRONTEND), "frontend"),
    (str(SCRIPTS), "scripts"),
    (str(ROOT / "data" / "input" / "MEMpreset.json"), "data/input"),
]
for package in ("openpyxl", "pandas"):
    datas += collect_data_files(package, include_py_files=False)

hiddenimports = PIPELINE_MODULES + collect_submodules("pywebview") + ["webview.platforms.edgechromium"]

a = Analysis(  # noqa: F821 — имена доступны в окружении PyInstaller
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(SCRIPTS)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Скрипты пайплайна импортируются вручную, их не видно в графе импортов
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

# Однофайловая сборка: COLLECT нет, всё содержимое уходит внутрь EXE.
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"{APP_NAME}-{APP_VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.exists() else None,
)