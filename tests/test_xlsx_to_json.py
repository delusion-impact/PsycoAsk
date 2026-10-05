import pandas as pd
import pytest

import xlsx_to_json


def make_xlsx(path, rows, columns):
    df = pd.DataFrame(rows, columns=columns)
    df.to_excel(path, index=False)
    return path


def test_parse_strips_whitespace_and_none(tmp_path):
    path = make_xlsx(
        tmp_path / "in.xlsx",
        [
            [" 1 ", "  Да  ", "   ", None],
            ["2", "Нет", "ответ", "x"],
        ],
        ["ID", "Вопрос?", "Пустой?", "Другое"],
    )
    records = xlsx_to_json.parse_xlsx_to_json(path)
    assert records[0]["Вопрос?"] == "Да"
    assert records[0]["Пустой?"] is None
    assert records[0]["Другое"] is None
    assert records[1]["ID"] == 2  # строка с цифрой → int


def test_duplicate_headers_get_suffixes(tmp_path):
    path = make_xlsx(tmp_path / "dup.xlsx", [["a", "b", "c"]], ["Вопрос", "Вопрос", "Вопрос"])
    records = xlsx_to_json.parse_xlsx_to_json(path)
    assert list(records[0].keys()) == ["Вопрос", "Вопрос_2", "Вопрос_3"]


def test_empty_rows_dropped(tmp_path):
    path = make_xlsx(tmp_path / "empty.xlsx", [["1", "Да"], [None, None], ["3", None]], ["ID", "Q"])
    records = xlsx_to_json.parse_xlsx_to_json(path)
    assert len(records) == 2


def test_empty_sheet_raises(tmp_path):
    path = tmp_path / "empty_sheet.xlsx"
    pd.DataFrame().to_excel(path, index=False)
    with pytest.raises(ValueError):
        xlsx_to_json.parse_xlsx_to_json(path)


def test_output_json_written(tmp_path):
    import json

    path = make_xlsx(tmp_path / "in.xlsx", [["1", "Да"]], ["ID", "Q"])
    out = tmp_path / "out" / "survey.json"
    xlsx_to_json.parse_xlsx_to_json(path, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == [{"ID": 1, "Q": "Да"}]
