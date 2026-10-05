import generate_data


def test_ids_unique_and_balanced(qa_fixture):
    records = generate_data.generate_records(50, qa_source=qa_fixture)
    assert len(records) == 50

    ids = [r["ID"] for r in records]
    assert len(set(ids)) == 50, "ID обязаны быть уникальными"

    male = sum(1 for r in records if r["Ваш пол / Мужской"] == "Мужской")
    female = sum(1 for r in records if r["Ваш пол / Женский"] == "Женский")
    assert male == 25
    assert female == 25
    # Мужской и Женский взаимно исключаются
    assert all(r["Ваш пол / Мужской"] is None or r["Ваш пол / Женский"] is None
               for r in records)


def test_values_come_from_qa(qa_fixture):
    import json

    qa = json.loads(qa_fixture.read_text(encoding="utf-8"))
    records = generate_data.generate_records(20, qa_source=qa_fixture)
    for record in records:
        for key, value in record.items():
            if key in ("ID", "Время создания"):
                continue
            assert value in qa[key] or value is None


def test_max_records_generateable(qa_fixture):
    records = generate_data.generate_records(generate_data.MAX_NUM_RECORDS,
                                             qa_source=qa_fixture)
    ids = {r["ID"] for r in records}
    assert len(ids) == generate_data.MAX_NUM_RECORDS
