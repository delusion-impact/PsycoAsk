import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from paths import GENERATED_JSON, QA_JSON, MEM_PRESET_JSON

NUM_RECORDS = 100
MAX_NUM_RECORDS = 1000

# Диапазоны для генерации
ID_MIN = 2525161289
ID_MAX = 2542538149
DATE_START = datetime(2026, 6, 1, 9, 0, 0)
DATE_END = datetime(2026, 9, 30, 21, 0, 0)

MALE_KEY = "Ваш пол / Мужской"
FEMALE_KEY = "Ваш пол / Женский"

# Пресеты режима «Сравнение»: по одной анкете на каждый профиль
COMPARISON_PRESETS = (
    "европейская семья 2026",
    "семья в рф 2026",
    "китайский вариант 2026",
)


def _preset_path(preset_source=None) -> Path:
    """Где лежит MEMpreset.json: явный путь → рабочая папка → файл из сборки.

    В EXE рабочая папка (%LOCALAPPDATA%) пуста при первом запуске, поэтому
    есть запасной путь — файл рядом со скриптами (data/input в сборке).
    """
    if preset_source:
        return Path(preset_source)
    if MEM_PRESET_JSON.exists():
        return MEM_PRESET_JSON
    bundled = Path(__file__).resolve().parent.parent / "data" / "input" / "MEMpreset.json"
    return bundled if bundled.exists() else MEM_PRESET_JSON


def available_presets(preset_source=None) -> list[str]:
    """Имена профилей респондентов из MEMpreset.json (пусто, если файла нет)."""
    path = _preset_path(preset_source)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("presets", {}))


def _load_preset(preset: str, qa_keys, preset_source=None) -> tuple[str, list[int]]:
    """Плоский список индексов профиля в порядке ключей qa.json.

    Блоки в presets идут в том же порядке, что и ключи qa.json; каждый
    индекс — позиция ответа в массиве вариантов вопроса: answer = qa[key][index].
    Имя профиля сравнивается без учёта регистра.
    """
    path = _preset_path(preset_source)
    if not path.exists():
        raise FileNotFoundError(f"Файл наборов ответов не найден: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    presets = data.get("presets", {})
    key = next((name for name in presets
                if name.strip().casefold() == preset.strip().casefold()), None)
    if key is None:
        raise ValueError(f"Неизвестный набор ответов «{preset}». Доступны: "
                         f"{', '.join(presets) or 'нет'}")
    indexes = [i for block in presets[key].values() for i in block]
    if len(indexes) != len(qa_keys):
        raise ValueError(f"Набор «{key}» задаёт {len(indexes)} индексов, "
                         f"а в словаре вопросов {len(qa_keys)}")
    return key, indexes


def random_datetime(start, end):
    delta = end - start
    rand_seconds = random.randint(0, int(delta.total_seconds()))
    return (start + timedelta(seconds=rand_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def generate_records(n, qa_source=None, preset=None, preset_source=None):
    """Генерирует n записей.

    qa_source — путь к словарю вопросов (по умолчанию QA_JSON).
    preset — имя профиля из MEMpreset.json: ответы берутся по индексам
    профиля (одинаковый профиль у всех записей, различаются ID и время).
    preset=None/пусто — случайные ответы, как обычно.
    """
    with open(Path(qa_source) if qa_source else QA_JSON, "r", encoding="utf-8") as f:
        qa = json.load(f)

    indexes = None
    preset_key = None
    if preset:
        preset_key, indexes = _load_preset(preset, list(qa), preset_source)
        for pos, (key, options) in enumerate(qa.items()):
            if not 0 <= indexes[pos] < len(options):
                raise ValueError(
                    f"Набор «{preset_key}»: индекс {indexes[pos]} вне диапазона "
                    f"вариантов вопроса «{key}» (0…{len(options) - 1})")

    records = []
    half = n // 2

    # ID обязаны быть уникальными: случайные randint могли дать дубликаты
    available = ID_MAX - ID_MIN + 1
    if n > available:
        raise ValueError(f"Нельзя сгенерировать {n} уникальных ID в диапазоне {ID_MIN}…{ID_MAX}")
    unique_ids = random.sample(range(ID_MIN, ID_MAX + 1), n)

    for i in range(n):
        record = {}

        # ID и время
        record["ID"] = unique_ids[i]
        record["Время создания"] = random_datetime(DATE_START, DATE_END)

        if indexes is not None:
            # Профиль респондента: answer = qa[key][index]
            for pos, (key, options) in enumerate(qa.items()):
                record[key] = options[indexes[pos]]
        else:
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


def generate_comparison_records(qa_source=None, preset_source=None) -> list[dict]:
    """Ровно три записи — по одной на каждый пресет из COMPARISON_PRESETS.

    Порядок фиксирован: Европа, РФ, Китай (так же выведены колонки отчёта).
    Каждая запись целиком собирается по индексам своего профиля.
    """
    with open(Path(qa_source) if qa_source else QA_JSON, "r", encoding="utf-8") as f:
        qa = json.load(f)
    qa_keys = list(qa)

    unique_ids = random.sample(range(ID_MIN, ID_MAX + 1), len(COMPARISON_PRESETS))
    records = []
    for slot, preset in enumerate(COMPARISON_PRESETS):
        preset_key, indexes = _load_preset(preset, qa_keys, preset_source)
        record = {"ID": unique_ids[slot],
                  "Время создания": random_datetime(DATE_START, DATE_END)}
        for pos, (key, options) in enumerate(qa.items()):
            if not 0 <= indexes[pos] < len(options):
                raise ValueError(
                    f"Набор «{preset_key}»: индекс {indexes[pos]} вне диапазона "
                    f"вариантов вопроса «{key}» (0…{len(options) - 1})")
            record[key] = options[indexes[pos]]
        records.append(record)
    return records


def generate_and_save(n: int = NUM_RECORDS, qa_source=None, output=None,
                      preset=None, preset_source=None,
                      compare: bool = False) -> list[dict]:
    """Генерирует записи и сохраняет их в GENERATED_JSON (или в output).

    compare=True — режим «Сравнение»: по одной анкете на каждый пресет
    COMPARISON_PRESETS (n и preset игнорируются).
    """
    if compare:
        records = generate_comparison_records(qa_source=qa_source,
                                              preset_source=preset_source)
    else:
        records = generate_records(n, qa_source=qa_source, preset=preset,
                                   preset_source=preset_source)
    out_path = Path(output) if output else Path(GENERATED_JSON)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    if compare:
        suffix = " (сравнение: Европа / РФ / Китай)"
    else:
        suffix = f" (набор «{preset}»)" if preset else ""
    print(f"✅ Сгенерировано {len(records)} записей{suffix} → {out_path}")
    return records


if __name__ == "__main__":
    preset_arg = sys.argv[2] if len(sys.argv) > 2 else None
    if len(sys.argv) > 1:
        if not sys.argv[1].isdigit() or not 1 <= int(sys.argv[1]) <= MAX_NUM_RECORDS:
            sys.exit(f"❌ Количество записей должно быть целым числом от 1 до {MAX_NUM_RECORDS}")
        generate_and_save(int(sys.argv[1]), preset=preset_arg)
    else:
        generate_and_save(NUM_RECORDS)