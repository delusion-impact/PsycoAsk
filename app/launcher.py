"""Окно приложения: pywebview, а при его отсутствии — браузер по умолчанию.

Сервер уже запущен в фоновом потоке, здесь только показывается окно и
следится за его закрытием. Результаты лежат в рабочей папке пользователя и
переживают перезапуск, поэтому временную папку заводить не нужно: чистить
при закрытии нечего.
"""

from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer

from app import APP_TITLE, APP_VERSION

WINDOW_SIZE = (1200, 800)
MIN_SIZE = (900, 620)
WEBVIEW2_KEY = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def stop_server(server: ThreadingHTTPServer) -> None:
    """Останавливает HTTP-сервер: до него окно уже закрыто, но keep-alive
    соединения ещё держат поток, поэтому shutdown идёт отдельным потоком."""
    threading.Thread(target=server.shutdown, daemon=True).start()


def run_window(server: ThreadingHTTPServer, port: int, token: str,
               browser: bool = False) -> int:
    """Показывает окно приложения. Возвращает код выхода."""
    url = f"http://127.0.0.1:{port}/?token={token}"

    if not browser:
        try:
            import webview  # noqa: PLC0415 — опциональная зависимость
        except ImportError:
            print("⚠️  pywebview не установлен — открываю интерфейс в браузере.")
            print("    pip install pywebview   (нужно для нативного окна)")
        else:
            return _run_webview(webview, server, url, port, token)

    print(f"\n  Интерфейс: {url}")
    print("  Остановить — Ctrl+C\n")
    try:
        while True:
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        print("\n  Остановлено.")
    finally:
        stop_server(server)
    return 0


def _run_webview(webview, server: ThreadingHTTPServer, url: str,
                 port: int, token: str) -> int:
    print(f"  Открываю окно: {url}")
    window = webview.create_window(APP_TITLE, url, width=WINDOW_SIZE[0],
                                  height=WINDOW_SIZE[1], min_size=MIN_SIZE,
                                  resizable=True)
    try:
        window.events.closing += lambda: stop_server(server)
        webview.start(debug=False)
    except Exception as exc:  # noqa: BLE001 — без WebView2 остаётся браузер
        print(f"⚠️  Не удалось открыть окно ({type(exc).__name__}: {exc})")
        print("   Открываю интерфейс в браузере.")
        return run_window(server, port, token, browser=True)
    finally:
        stop_server(server)
    return 0


def webview2_available() -> bool:
    """На Windows окно pywebview требует WebView2 Runtime."""
    if sys.platform != "win32":
        return True
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_KEY) as key:
            return bool(winreg.QueryValueEx(key, "pv")[0])
    except OSError:
        return False


def pick_backend() -> tuple[bool, str]:
    """(есть ли pywebview, строка для вывода при запуске)."""
    try:
        import webview  # noqa: F401,PLC0415
    except ImportError:
        return False, "не установлен — откроется браузер"
    if not webview2_available():
        return False, "нет WebView2 Runtime — откроется браузер"
    return True, "нативное окно (WebView2)"


__all__ = ["run_window", "pick_backend", "stop_server", "webview2_available", "APP_VERSION"]