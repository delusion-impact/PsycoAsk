from pathlib import Path

import pytest

import txt_to_qa

REF = Path(__file__).resolve().parent.parent / "data" / "input" / "ref_txt.txt"


@pytest.mark.skipif(not REF.exists(), reason="нет data/input/ref_txt.txt")
def test_parses_all_blocks():
    qa = txt_to_qa.build_qa(REF)
    assert len(qa) == 181

    # Тест 0: пол разбит на два столбца
    assert qa["Ваш пол / Мужской"] == [None, "Мужской"]
    assert qa["Ваш пол / Женский"] == [None, "Женский"]
    assert "Сколько вам лет?" in qa

    # Тест 2: 69 вариантов утверждений с суффиксами
    test2 = [key for key in qa if key.startswith("Выберите утверждение")]
    assert len(test2) == 69
    assert test2[0] == "Выберите утверждение, которое больше про вас:"
    assert test2[1] == "Выберите утверждение, которое больше про вас:_2"
    # У каждого пункта Теста 2 ровно две альтернативы А/Б
    assert all(len(qa[key]) == 2 for key in test2)

    # Тест 1/3/4: варианты ответов не пустые
    assert qa["Мне трудно зависеть от других людей"]
    assert all(options for key, options in qa.items() if key not in test2)
