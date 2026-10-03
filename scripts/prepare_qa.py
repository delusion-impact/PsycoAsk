import json
from collections import defaultdict
from pathlib import Path

from paths import QA_JSON, SURVEY_JSON

EXCLUDE_KEYS = {"ID", "Время создания"}

def prepare_qa(source=None, output=None):
    """Собирает qa.json из распарсенных ответов.

    source/output необязательны: по умолчанию читается SURVEY_JSON и пишется
    QA_JSON, как в консольном запуске.
    """
    source = Path(source) if source else Path(SURVEY_JSON)
    output = Path(output) if output else Path(QA_JSON)

    with open(source, "r", encoding="utf-8") as f:
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

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(qa_result, f, ensure_ascii=False, indent=2)

    print(f"✅ QA-словарь создан: {output}")
    print(f"   Всего вопросов: {len(qa_result)}")
    return qa_result

if __name__ == "__main__":
    prepare_qa()