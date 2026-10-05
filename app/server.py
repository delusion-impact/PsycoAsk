"""Локальный HTTP-сервер: JSON-API и раздача веб-интерфейса.

Сервер поднимается на 127.0.0.1 и случайном свободном порту, а все запросы
/api/* требуют токен запуска: без него любой сайт в браузере мог бы слать
команды локальному приложению.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app import APP_TITLE, APP_VERSION, bridge, config
from app.jobs import JOBS, Progress

HOST = "127.0.0.1"
TOKEN_HEADER = "X-PsycoAsk-Token"
MAX_BODY_BYTES = 96 * 1024 * 1024


class ApiError(Exception):
    """Ошибка, которую видно пользователю в интерфейсе."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.message = message
        self.status = int(status)


class PsycoAskHandler(BaseHTTPRequestHandler):
    server_version = f"PsycoAsk/{APP_VERSION}"
    protocol_version = "HTTP/1.1"
    token = ""
    _raw_body = b""

    # --- Служебное ---

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # логи сервера в UI не нужны

    def log_error(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    # --- Ответы ---

    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _fail(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"ok": False, "error": message}, status)

    # --- Разбор запроса ---

    def _read_body(self) -> bytes:
        """Читает тело запроса целиком.

        Тело обязательно дочитывается для каждого POST, даже если обработчик
        его не использует: соединение живёт (keep-alive), и непрочитанные
        байты сервер принял бы за начало следующего запроса — тот падал бы
        с 501, а интерфейс сообщал бы «Ошибка 501» на пустом месте.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ApiError("Некорректный Content-Length") from exc
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            raise ApiError("Слишком большой запрос")
        return self.rfile.read(length)

    def _body(self) -> bytes:
        return self._raw_body

    def _json_body(self) -> dict[str, Any]:
        raw = self._raw_body
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiError(f"Некорректный JSON: {exc}") from exc
        return payload if isinstance(payload, dict) else {"value": payload}

    @staticmethod
    def _query(path: str) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlparse(path).query).items()}

    def _authorized(self, query: dict[str, str]) -> bool:
        supplied = self.headers.get(TOKEN_HEADER) or query.get("token") or ""
        return bool(self.token) and secrets.compare_digest(supplied, self.token)

    @staticmethod
    def _disposition_param(header: str, key: str) -> str:
        """Значение параметра заголовка Content-Disposition: filename="x.xlsx"."""
        pattern = rf'{key}\s*=\s*"([^"]*)"'
        match = re.search(pattern, header, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(rf'{key}\s*=\s*([^;]+)', header, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _body_from_multipart(self, raw: bytes) -> tuple[str, bytes]:
        """Достаёт первый файл из multipart/form-data."""
        content_type = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in content_type:
            raise ApiError("Ожидается multipart/form-data")

        boundary = self._disposition_param(content_type, "boundary")
        if not boundary:
            raise ApiError("Не найдена граница multipart")

        marker = b"--" + boundary.encode("latin-1")
        for chunk in raw.split(marker):
            if not chunk or chunk in (b"--\r\n", b"--"):
                continue
            head, separator, payload = chunk.partition(b"\r\n\r\n")
            if not separator:
                continue
            payload = payload.rsplit(b"\r\n", 1)[0]
            # Имя файла берём только из заголовка Content-Disposition: иначе
            # значением окажется тип MIME, а он выглядит как путь с расширением
            name = self._disposition_param(head.decode("utf-8", "replace"), "filename")
            if name:
                return name, payload
        raise ApiError("Файл в запросе не найден")

    # --- Маршрутизация ---

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        # Предварительный запрос браузера. Отвечаем разрешением, иначе
        # http.server отвечает на OPTIONS кодом 501.
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        # CORS разрешаем только самому приложению; отражать любой Origin
        # нельзя — токен тоже идёт в ответе при GET /
        origin = self.headers.get("Origin", "")
        hostname = urlparse(origin).hostname if origin else ""
        if hostname in ("127.0.0.1", "localhost", "::1"):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", f"{TOKEN_HEADER}, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = self._query(self.path)
        self._raw_body = b""
        try:
            if method == "POST":
                # Читаем тело до разбора маршрута: так ни один обработчик
                # не оставит его непрочитанным (см. _read_body).
                self._raw_body = self._read_body()

            if route.startswith("/api/"):
                self._api(method, route, query)
            elif method == "GET":
                self._static(route)
            else:
                self._fail("Метод не поддерживается", HTTPStatus.METHOD_NOT_ALLOWED)
        except ApiError as exc:
            self._fail(exc.message, exc.status)
        except ValueError as exc:
            # Ошибки валидации уровня "файл больше N МБ" показываем как 400,
            # а не как 500
            self._fail(str(exc), HTTPStatus.BAD_REQUEST)
        except PermissionError as exc:
            self._fail(str(exc), HTTPStatus.FORBIDDEN)
        except FileNotFoundError as exc:
            self._fail(str(exc), HTTPStatus.NOT_FOUND)
        except BrokenPipeError:
            pass  # клиент закрыл вкладку во время ответа
        except Exception as exc:  # noqa: BLE001
            self._fail(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    # --- API ---

    def _api(self, method: str, route: str, query: dict[str, str]) -> None:
        if not self._authorized(query):
            self._fail("Нет доступа", HTTPStatus.FORBIDDEN)
            return

        if route == "/api/state" and method == "GET":
            self._json({"ok": True, "state": bridge.state()})
        elif route == "/api/health" and method == "GET":
            self._json({"ok": True, "app": APP_TITLE, "version": APP_VERSION,
                        "workspace": str(bridge.WORKSPACE)})
        elif route == "/api/upload" and method == "POST":
            name, payload = self._body_from_multipart(self._body())
            path = bridge.store_upload(name, payload)
            self._json({"ok": True, "name": path.name, "size": len(payload),
                        "inputs": bridge.list_inputs()})
        elif route == "/api/parse" and method == "POST":
            body = self._json_body()
            filename = str(body.get("file") or "").strip()
            if not filename:
                raise ApiError("Не выбран файл выгрузки")
            bridge.resolve_input(filename)  # проверяем сразу, а не в фоне
            job = JOBS.submit("parse", lambda progress: bridge.parse_input(filename, progress))
            self._json({"ok": True, "job": job.snapshot()})
        elif route == "/api/generate" and method == "POST":
            body = self._json_body()
            generator = bridge.module("generate_data")
            bars = bool(body.get("bars", False))
            count = body.get("count", generator.NUM_RECORDS)
            try:
                count = int(count)
            except (TypeError, ValueError) as exc:
                raise ApiError("Количество анкет должно быть числом") from exc
            if not 1 <= count <= generator.MAX_NUM_RECORDS:
                raise ApiError(f"Количество анкет: от 1 до {generator.MAX_NUM_RECORDS}")
            preset = str(body.get("preset") or "").strip()
            compare = bool(body.get("compare", False))
            if compare:
                known = {name.casefold()
                         for name in generator.available_presets()}
                missing = [p for p in generator.COMPARISON_PRESETS
                           if p.casefold() not in known]
                if missing:
                    raise ApiError("Нет пресетов для сравнения: "
                                   + ", ".join(missing))
            elif preset:
                known = generator.available_presets()
                if not any(preset.casefold() == name.casefold() for name in known):
                    raise ApiError(f"Неизвестный набор ответов: «{preset}»")
            if not Path(bridge.paths().QA_JSON).exists():
                raise ApiError("Сначала разберите выгрузку: нет словаря вопросов")
            job = JOBS.submit("generate",
                              lambda progress: bridge.generate(count, progress,
                                                               bars=bars,
                                                               preset=preset or None,
                                                               compare=compare))
            self._json({"ok": True, "job": job.snapshot()})
        elif route == "/api/jobs" and method == "GET":
            self._json({"ok": True, "jobs": JOBS.list(), "active": JOBS.active})
        elif route.startswith("/api/jobs/") and method == "GET":
            job = JOBS.get(route.rsplit("/", 1)[-1])
            if job is None:
                raise ApiError("Задача не найдена", HTTPStatus.NOT_FOUND)
            self._json({"ok": True, "job": job.snapshot()})
        elif route == "/api/open" and method == "POST":
            # Файлы открываются в Проводнике, а не отдаются ссылкой: обычная
            # ссылка не передаёт токен, и страница приложения заменялась бы
            # ответом сервера.
            path = bridge.resolve_in_workspace(query.get("path", ""))
            reveal(path)
            self._json({"ok": True})
        else:
            self._fail("Неизвестный метод API", HTTPStatus.NOT_FOUND)

    # --- Файлы ---

    def _static(self, route: str) -> None:
        if route in ("/", "/index.html"):
            page = (config.frontend_dir() / "index.html").read_bytes()
            # Токен отдаём прямо в разметке: иначе страница не знает, куда
            # стучаться, а хранить его в JS-константе сборки нельзя.
            html = page.decode("utf-8").replace("__APP_TOKEN__", self.token)
            html = html.replace("__APP_VERSION__", APP_VERSION)
            self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        name = Path(route).name
        if "/" in route.strip("/"):
            name = route.strip("/")
        target = (config.frontend_dir() / name).resolve()
        folder = config.frontend_dir().resolve()
        if folder not in target.parents or not target.is_file():
            self._fail("Страница не найдена", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), content_type)


def reveal(path: Path) -> None:
    """Открывает файл или его папку в Проводнике."""
    import os
    import subprocess
    import sys as _sys

    target = str(path)
    if _sys.platform == "win32":
        if Path(target).is_file():
            # Флаг и путь — одним аргументом, иначе explorer открывает
            # файл вместо выделения его в Проводнике
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            os.startfile(target)  # noqa: S606 — стандартный Проводник Windows
    elif _sys.platform == "darwin":
        subprocess.Popen(["open", "-R", target])
    else:
        subprocess.Popen(["xdg-open", str(Path(target).parent)])


def make_server(port: int = 0) -> tuple[ThreadingHTTPServer, str, str]:
    """Поднимает сервер и возвращает (сервер, порт, токен)."""
    token = secrets.token_urlsafe(24)
    handler = type("BoundHandler", (PsycoAskHandler,), {"token": token})
    server = ThreadingHTTPServer((HOST, port), handler)
    server.daemon_threads = True
    return server, server.server_address[1], token


def serve_in_background(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread