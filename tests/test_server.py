import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.server import make_server, serve_in_background


@pytest.fixture(scope="module")
def server():
    httpd, port, token = make_server(0)
    thread = serve_in_background(httpd)
    yield port, token
    httpd.shutdown()
    httpd.server_close()


def get(port, path, token=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        request.add_header("X-PsycoAsk-Token", token)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post(port, path, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                     method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-PsycoAsk-Token", token)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_index_embeds_token(server):
    port, token = server
    status, body = get(port, "/")
    assert status == 200
    assert "__APP_TOKEN__" not in body
    assert token in body


def test_api_requires_token(server):
    port, token = server
    status, _ = get(port, "/api/state")
    assert status == 403
    status, body = get(port, "/api/state", token=token)
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_open_rejects_escape(server):
    port, token = server
    status, body = post(port, "/api/open?path=../secret", {}, token=token)
    assert status == 403


def test_generate_validates_count(server):
    port, token = server
    status, body = post(port, "/api/generate", {"count": "не число"}, token=token)
    assert status == 400
    assert "числом" in json.loads(body)["error"]


def test_generate_rejects_unknown_preset(server):
    port, token = server
    status, body = post(port, "/api/generate", {"count": 5, "preset": "нет такого"},
                        token=token)
    assert status == 400
    assert "Неизвестный набор" in json.loads(body)["error"]


def test_generate_compare_mode(server):
    """Режим «Сравнение»: пресеты проверяются по MEMpreset.json, а не по preset."""
    port, token = server
    from app import bridge

    # preset игнорируется в режиме сравнения — валить должен только qa.json
    status, body = post(port, "/api/generate",
                        {"count": 100, "preset": "мусор", "compare": True},
                        token=token)
    if Path(bridge.paths().QA_JSON).exists():
        assert status == 200, body
        assert json.loads(body)["ok"] is True
    else:
        assert status == 400
        assert "нет словаря" in json.loads(body)["error"]
