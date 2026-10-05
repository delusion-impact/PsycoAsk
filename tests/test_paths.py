import re

import paths


def test_stamped_appends_stamp():
    stamped = paths.stamped(paths.REPORT_XLSX)
    assert re.fullmatch(r"visualization_report_\d{8}-\d{6}\.xlsx", stamped.name)


def test_run_stamp_env_override(monkeypatch):
    monkeypatch.setenv(paths.STAMP_ENV, "20260102-030405")
    assert paths.run_stamp() == "20260102-030405"
