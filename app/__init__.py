"""Гибридное приложение PsycoAsk: веб-интерфейс поверх консольного пайплайна.

Логика пайплайна не переписана — она осталась в scripts/ и вызывается отсюда
как обычные функции. Этот пакет отвечает только за HTTP-слой и окно.
"""

from __future__ import annotations

import os
import sys

# Agg обязан быть выбран до первого импорта matplotlib: без него скрипты
# визуализации открывают окна графиков и блокируют фоновый поток задачи.
os.environ.setdefault("MPLBACKEND", "Agg")


def _ensure_stdio() -> None:
    """Готовит вывод к печати служебных сообщений пайплайна.

    В сборке без консоли PyInstaller подставляет вместо sys.stdout заглушку с
    системной кодировкой (cp1251/cp1252), и первый же print() с эмодзи падает
    с UnicodeEncodeError, утаскивая за собой весь шаг. Заглушка переводится на
    UTF-8, а настоящей консоли меняется только обработка ошибок, чтобы не
    превращать вывод в крякозябры.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            continue
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


_ensure_stdio()

APP_NAME = "PsycoAsk"
APP_TITLE = "PsycoAsk — генерация анкет"
APP_VERSION = "1.1.0"

__all__ = ["APP_NAME", "APP_TITLE", "APP_VERSION"]