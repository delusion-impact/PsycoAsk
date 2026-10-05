import json
import os
from pathlib import Path

import pytest

from app import bridge


def test_safe_name():
    assert bridge.safe_name("../../etc/passwd") == "passwd"
    assert bridge.safe_name('a<b>:"|?*.xlsx') == "a_b______.xlsx"
    assert bridge.safe_name("") == "upload.xlsx"


def test_store_upload_never_overwrites():
    first = bridge.store_upload("form.xlsx", b"data1")
    second = bridge.store_upload("form.xlsx", b"data2")
    assert first.name != second.name
    assert first.read_bytes() == b"data1"
    assert second.read_bytes() == b"data2"


def test_store_upload_rejects_oversize(monkeypatch):
    monkeypatch.setattr(bridge, "MAX_UPLOAD_BYTES", 3)
    with pytest.raises(ValueError):
        bridge.store_upload("big.xlsx", b"1234")


def test_resolve_in_workspace_blocks_escape(workspace):
    with pytest.raises(PermissionError):
        bridge.resolve_in_workspace("../secret.txt")


def _touch(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_artifacts_filters_exact_stamp():
    generated = bridge.data_dir("generated")
    reports = bridge.WORKSPACE / "output" / "reports"
    _touch(generated / "generated_survey_20260101-010101.xlsx")
    _touch(reports / "visualization_report_20260101-010101.xlsx")
    _touch(generated / "generated_survey_20260101-010101_backup.xlsx")  # другой штамп? нет — тот же штамп в stem
    _touch(reports / "visualization_report_20260202-020202.xlsx")

    items = bridge.artifacts()
    names = {item["name"] for item in items}
    assert f"generated_survey_20260202-020202.xlsx" not in names  # max stamp
    # "backup"-файл имеет штамп 20260101-010101 — не должен попадать при
    # выборе последнего прогона (max = 20260202)
    assert "generated_survey_20260101-010101_backup.xlsx" not in names
    assert all(item["category"] in {"generate", "visualize"} for item in items)


def test_state_has_no_side_effects(workspace, monkeypatch):
    # Готовим промежуточные файлы напрямую
    import paths as core

    qa = {"Q": ["A", "B"]}
    core.QA_JSON.parent.mkdir(parents=True, exist_ok=True)
    core.QA_JSON.write_text(json.dumps(qa), encoding="utf-8")
    core.SURVEY_JSON.write_text(json.dumps([{"ID": 1, "Q": "A"}]), encoding="utf-8")
    core.GENERATED_JSON.parent.mkdir(parents=True, exist_ok=True)
    core.GENERATED_JSON.write_text(json.dumps([{"ID": 1}, {"ID": 2}]), encoding="utf-8")

    monkeypatch.delenv("PSYCOASK_STAMP", raising=False)
    stamp_file = bridge.STAMP_FILE
    if stamp_file.exists():
        stamp_file.unlink()

    info = bridge.state()

    assert info["questions"] == 1
    assert info["generated_records"] == 2
    assert info["max_count"] > 0
    assert not stamp_file.exists(), "state() не должен создавать run_stamp.txt"
    assert "PSYCOASK_STAMP" not in os.environ, "state() не должен менять окружение"


def test_generated_records_cache(tmp_path):
    import paths as core

    core.GENERATED_JSON.parent.mkdir(parents=True, exist_ok=True)
    core.GENERATED_JSON.write_text(json.dumps([{"ID": 1}]), encoding="utf-8")
    assert bridge._generated_records() == 1
    core.GENERATED_JSON.write_text(json.dumps([{"ID": 1}, {"ID": 2}]), encoding="utf-8")
    assert bridge._generated_records() == 2
