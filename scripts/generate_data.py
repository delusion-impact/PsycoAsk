import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from paths import GENERATED_JSON, QA_JSON

NUM_RECORDS = 100
MAX_NUM_RECORDS = 1000

# Диапазоны для генерации
ID_MIN = 2525161289
ID_MAX = 2542538149
DATE_START = datetime(2026, 6, 1, 9, 0, 0)
DATE_END = datetime(2026, 9, 30, 21, 0, 0)

MALE_KEY = "Ваш пол / Мужской"
FEMALE_KEY = "Ваш пол / Женский"


def random_datetime(start, end):
    delta = end - start
    rand_seconds = random.randint(0, int(delta.total_seconds()))
    return (start + timedelta(seconds=rand_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def generate_records(n):
    with open(QA_JSON, "r", encoding="utf-8") as f:
        qa = json.load(f)

    records = []
    half = n // 2

    for i in range(n):
        record = {}

        # ID и время
        record["ID"] = random.randint(ID_MIN, ID_MAX)
        record["Время создания"] = random_datetime(DATE_START, DATE_END)

        # Баланс пола: первая половина — женский, вторая — мужской
        is_female = i < half
        for key, options in qa.items():
            if key == MALE_KEY:
                record[key] = "Мужской" if not is_female else None
            elif key == FEMALE_KEY:
                record[key] = "Женский" if is_female else None
            else:
                record[key] = random.choice(options)

        records.append(record)

    # Перемешиваем, чтобы мужские и женские записи не шли блоками
    random.shuffle(records)
    return records


def generate_and_save(n: int = NUM_RECORDS) -> list[dict]:
    """Генерирует n записей и сохраняет их в GENERATED_JSON."""
    records = generate_records(n)
    Path(GENERATED_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(GENERATED_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"✅ Сгенерировано {n} записей → {GENERATED_JSON}")
    return records


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if not sys.argv[1].isdigit() or not 1 <= int(sys.argv[1]) <= MAX_NUM_RECORDS:
            sys.exit(f"❌ Количество записей должно быть целым числом от 1 до {MAX_NUM_RECORDS}")
        generate_and_save(int(sys.argv[1]))
    else:
        generate_and_save(NUM_RECORDS)