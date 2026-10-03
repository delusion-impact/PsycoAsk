"""Пути приложения и выбор рабочей папки.

Сборка EXE разворачивается в Program Files, писать туда нельзя, поэтому
рабочие данные живут в отдельной папке пользователя, а код и статика
читаются из каталога сборки.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app import APP_NAME

# === Каталоги приложения ===

def is_frozen() -> bool:
    """True для сборки PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Корень с кодом и статикой: папка сборки или корень проекта."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def scripts_dir() -> Path:
    return resource_root() / "scripts"


def frontend_dir() -> Path:
    return resource_root() / "frontend"


# === Рабочее пространство ===

def project_root() -> Path:
    """Корень проекта при запуске из исходников."""
    return Path(__file__).resolve().parent.parent


def default_workspace() -> Path:
    """Куда складывать data/ и output/.

    Порядок: явное PSYCOASK_HOME → папка приложения в профиле пользователя
    для EXE → корень проекта при запуске из исходников.
    """
    override = os.environ.get("PSYCOASK_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if is_frozen():
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        base = Path(local) if local else Path.home()
        return base / APP_NAME

    return project_root()


def setup_workspace() -> Path:
    """Готовит рабочую папку и прокидывает её в scripts/paths.py.

    Переменная выставляется до первого импорта paths: модуль читает её при
    загрузке и строит все остальные пути от неё.
    """
    workspace = default_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["PSYCOASK_HOME"] = str(workspace)
    return workspace


def relative(path) -> str:
    """Путь относительно рабочей папки в unix-виде — для JSON и интерфейса."""
    path = Path(path)
    for base in (default_workspace(), resource_root()):
        try:
            return path.resolve().relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()