"""Сквозной прогон пайплайна на настоящем источнике data/input/ref_txt.txt."""

import json
import shutil
from pathlib import Path

import pytest

from app import bridge

REF = Path(__file__).resolve().parent.parent / "data" / "input" / "ref_txt.txt"


@pytest.mark.skipif(not REF.exists(), reason="нет data/input/ref_txt.txt")
def test_full_pipeline(workspace):
    # Готовим выгрузку в рабочей папке тестового workspace
    target = bridge.data_dir("input") / REF.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REF, target)

    parse_result = bridge.parse_input(REF.name)
    assert parse_result["questions"] > 0
    assert parse_result["answers"] > 0

    gen = bridge.generate(10, bars=True)
    assert gen["count"] == 10
    assert gen["preset"] is None
    assert (bridge.WORKSPACE / gen["xlsx"]).exists()
    assert (bridge.WORKSPACE / gen["bars"]).exists()

    # Профиль из MEMpreset.json: одинаковые ответы у всех записей,
    # ID и время остаются разными
    mem = REF.parent / "MEMpreset.json"
    if mem.exists():
        shutil.copy(mem, bridge.data_dir("input") / mem.name)
        preset_run = bridge.generate(5, preset="семья в рф 2026")
        assert preset_run["preset"] == "семья в рф 2026"
        generated = json.loads(
            (bridge.WORKSPACE / bridge.paths().GENERATED_JSON)
            .read_text(encoding="utf-8"))
        answers = [{k: v for k, v in record.items()
                    if k not in ("ID", "Время создания")} for record in generated]
        assert len(answers) == 5
        assert all(item == answers[0] for item in answers)
        assert len({r["ID"] for r in generated}) == 5

        # Режим «Сравнение»: count/bars игнорируются, по анкете на пресет
        # и вместо data bars — аналитический отчёт
        compare_run = bridge.generate(50, bars=True, compare=True)
        assert compare_run["compare"] is True
        assert compare_run["count"] == 3
        assert "bars" not in compare_run
        assert (bridge.WORKSPACE / compare_run["report"]).exists()
        generated = json.loads(
            (bridge.WORKSPACE / bridge.paths().GENERATED_JSON)
            .read_text(encoding="utf-8"))
        assert len(generated) == 3
        answers = [{k: v for k, v in record.items()
                    if k not in ("ID", "Время создания")} for record in generated]
        # Профили культур разные → анкеты не совпадают друг с другом
        assert answers[0] != answers[1]

    # Результаты видны в состоянии приложения с одним штампом
    info = bridge.state()
    assert info["generated"] is True
    assert info["artifacts"]
