"""Точка входа гибридного приложения PsycoAsk.

    python main.py              # окно приложения (pywebview или браузер)
    python main.py --browser    # принудительно в браузере
    python main.py --port 8750  # заданный порт вместо случайного
    python main.py --serve-only # сервер без окна, адрес печатается в консоль

Порт по умолчанию выбирается системой (0): приложение можно запускать
несколько раз одновременно, и второй экземпляр не упадёт из-за конфликта.

Консольный пайплайн остаётся рабочим как есть:

    python scripts/run_pipeline.py
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
import webbrowser
from datetime import datetime

from app import APP_NAME, APP_TITLE, APP_VERSION, bridge, config, launcher, server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_TITLE} — веб-интерфейс над консольным пайплайном.")
    parser.add_argument("--port", type=int, default=0,
                        help="порт сервера (0 — выбрать свободный, по умолчанию)")
    parser.add_argument("--browser", action="store_true",
                        help="открыть интерфейс в браузере вместо нативного окна")
    parser.add_argument("--serve-only", action="store_true",
                        help="только сервер, без окна; работает до Ctrl+C")
    parser.add_argument("--no-open", action="store_true",
                        help="запустить сервер, не открывая интерфейс")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def wait_until_interrupted() -> int:
    """Держит процесс живым до Ctrl+C."""
    try:
        while True:
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        print("\n  Остановлено.")
    return 0


def report_crash(exc: BaseException) -> int:
    """Пишет журнал падения: в сборке без консоли иначе его не увидеть."""
    log_path = bridge.WORKSPACE / "crash.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
            log.write("".join(traceback.format_exception(exc)))
    except OSError:
        pass

    print(f"⚠️  Приложение не запустилось: {exc}")
    print(f"   Подробности: {log_path}")
    try:
        os.startfile(log_path)  # noqa: S606 — открыть журнал в редакторе
    except (OSError, AttributeError):
        pass
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    httpd, port, token = server.make_server(args.port)
    server.serve_in_background(httpd)
    url = f"http://{server.HOST}:{port}/"

    windowed, note = launcher.pick_backend()
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"  Рабочая папка: {bridge.WORKSPACE}")
    print(f"  Скрипты:       {config.scripts_dir()}")
    print(f"  Окно:          {note}")
    print(f"  Сервер:        {url}")

    try:
        if args.serve_only or args.no_open:
            if not args.no_open:
                webbrowser.open(url)
            return wait_until_interrupted()
        return launcher.run_window(httpd, port, token,
                                   browser=args.browser or not windowed)
    except KeyboardInterrupt:
        print("\n  Остановлено.")
        return 0
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 — последний рубеж для сборки без консоли
        sys.exit(report_crash(error))