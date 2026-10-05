import json

import prepare_qa


def test_qa_sorted_deterministic_and_excludes_service(tmp_path):
    survey = [
        {"ID": 1, "Время создания": "2026-01-01", "Q1": "Б", "Q2": None},
        {"ID": 2, "Время создания": "2026-01-02", "Q1": "А", "Q2": "Да"},
        {"ID": 3, "Время создания": "2026-01-03", "Q1": None, "Q2": "Да"},
    ]
    src = tmp_path / "survey.json"
    src.write_text(json.dumps(survey, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "qa.json"

    qa1 = prepare_qa.prepare_qa(src, out)
    qa2 = prepare_qa.prepare_qa(src, out)

    assert set(qa1) == {"Q1", "Q2"}  # ID и Время создания исключены
    assert qa1 == qa2  # повторный прогон даёт то же самое
    assert qa1["Q2"] == ["Да", None]  # None — последний, остальные отсортированы
    assert qa1["Q1"] == ["А", "Б", None]
