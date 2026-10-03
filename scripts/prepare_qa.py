import json
from collections import defaultdict
from pathlib import Path

from paths import QA_JSON, SURVEY_JSON

EXCLUDE_KEYS = {"ID", "Время создания"}

def prepare_qa():
    with open(SURVEY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    qa_map = defaultdict(set)

    for record in data:
        for key, value in record.items():
            if key in EXCLUDE_KEYS:
                continue
            # Сохраняем None как отдельный вариант ответа
            qa_map[key].add(value)

    # Преобразуем set в list для сериализации в JSON
    qa_result = {k: list(v) for k, v in qa_map.items()}

    Path(QA_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(QA_JSON, "w", encoding="utf-8") as f:
        json.dump(qa_result, f, ensure_ascii=False, indent=2)

    print(f"✅ QA-словарь создан: {QA_JSON}")
    print(f"   Всего вопросов: {len(qa_result)}")

if __name__ == "__main__":
    prepare_qa()