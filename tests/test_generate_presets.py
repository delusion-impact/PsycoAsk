"""Профили респондентов из data/input/MEMpreset.json.

Каждый элемент массива индексов профиля соответствует вопросу в порядке
ключей qa.json: answer = qa[key][index].
"""

import json
from pathlib import Path

import pytest

import generate_data
import txt_to_qa

REPO = Path(__file__).resolve().parent.parent
MEM = REPO / "data" / "input" / "MEMpreset.json"
REF = REPO / "data" / "input" / "ref_txt.txt"

# Имена, которые предлагает интерфейс на шаге «2 Генерация»
UI_PRESETS = ("семья в рф 2026", "китайский вариант 2026", "европейская семья 2026")


def _write_preset(path: Path, blocks: dict, name: str = "профиль") -> Path:
    path.write_text(json.dumps({"presets": {name: blocks}}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def test_preset_answers_follow_indexes(qa_fixture, tmp_path):
    qa = json.loads(qa_fixture.read_text(encoding="utf-8"))
    indexes = [1, 0, 2, 3]  # Мужской / null / Возраст / Скорее не согласен
    preset_file = _write_preset(tmp_path / "mem.json",
                                {"демография": indexes[:2], "шкалы": indexes[2:]})

    records = generate_data.generate_records(
        5, qa_source=qa_fixture, preset="ПРОФИЛЬ",  # регистр имени не важен
        preset_source=preset_file)

    assert len(records) == 5
    expected = {key: options[i]
                for (key, options), i in zip(qa.items(), indexes)}
    for record in records:
        assert {k: v for k, v in record.items()
                if k not in ("ID", "Время создания")} == expected
    assert len({r["ID"] for r in records}) == 5  # ID всё равно уникальны


def test_random_mode_still_works_without_preset(qa_fixture):
    records = generate_data.generate_records(10, qa_source=qa_fixture)
    assert len(records) == 10


def test_unknown_preset_rejected(qa_fixture, tmp_path):
    preset_file = _write_preset(tmp_path / "mem.json", {"b": [1, 0, 2, 3]})
    with pytest.raises(ValueError, match="Неизвестный набор"):
        generate_data.generate_records(1, qa_source=qa_fixture,
                                       preset="нет такого",
                                       preset_source=preset_file)


def test_out_of_range_index_rejected(qa_fixture, tmp_path):
    preset_file = _write_preset(tmp_path / "mem.json", {"b": [9, 0, 1, 2]})
    with pytest.raises(ValueError, match="вне диапазона"):
        generate_data.generate_records(1, qa_source=qa_fixture,
                                       preset="профиль",
                                       preset_source=preset_file)


def test_wrong_index_count_rejected(qa_fixture, tmp_path):
    preset_file = _write_preset(tmp_path / "mem.json", {"b": [1, 0]})  # нужно 4
    with pytest.raises(ValueError, match="индексов"):
        generate_data.generate_records(1, qa_source=qa_fixture,
                                       preset="профиль",
                                       preset_source=preset_file)


def test_available_presets_without_file(tmp_path):
    assert generate_data.available_presets(tmp_path / "нет.json") == []


def test_preset_falls_back_to_bundled_file(tmp_path, monkeypatch):
    # Рабочая папка пуста (первый запуск EXE) → берём файл из сборки/исходников
    monkeypatch.setattr(generate_data, "MEM_PRESET_JSON", tmp_path / "нет.json")
    path = generate_data._preset_path()
    assert path.exists()
    assert set(UI_PRESETS) <= {name.casefold()
                               for name in generate_data.available_presets()}


@pytest.mark.skipif(not MEM.exists(), reason="нет data/input/MEMpreset.json")
def test_workspace_gets_preset_seeded(workspace):
    from app import config

    ws = config.setup_workspace()
    seeded = ws / "data" / "input" / "MEMpreset.json"
    assert seeded.exists(), "MEMpreset.json должен подсеиваться в рабочую папку"
    known = {name.casefold() for name in generate_data.available_presets()}
    assert set(UI_PRESETS) <= known


@pytest.mark.skipif(not (MEM.exists() and REF.exists()),
                    reason="нет data/input/MEMpreset.json или ref_txt.txt")
def test_real_presets_match_real_qa():
    qa = txt_to_qa.build_qa(REF)
    presets = generate_data.available_presets(MEM)
    for name in UI_PRESETS:
        assert any(name.casefold() == p.casefold() for p in presets), \
            f"в MEMpreset.json нет профиля «{name}» для кнопки в интерфейсе"

    data = json.loads(MEM.read_text(encoding="utf-8"))["presets"]
    for name, blocks in data.items():
        indexes = [i for block in blocks.values() for i in block]
        assert len(indexes) == len(qa), f"«{name}»: индексов не хватает"
        for (key, options), i in zip(qa.items(), indexes):
            assert 0 <= i < len(options), f"«{name}»: индекс {i} вне вариантов «{key}»"
            _ = options[i]  # профиль разрешается в текстовый ответ
