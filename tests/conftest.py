import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="psycoask_test_"))

# ВАЖНО: переменная читается при импорте scripts/paths.py и app/config.py,
# поэтому выставляем её до любых импортов приложения.
os.environ["PSYCOASK_HOME"] = str(WORK)
os.environ.pop("PSYCOASK_STAMP", None)

for folder in (ROOT, ROOT / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def workspace() -> Path:
    return WORK


@pytest.fixture()
def qa_fixture(tmp_path) -> Path:
    import json

    qa = {
        "Ваш пол / Мужской": ["Мужской", None],
        "Ваш пол / Женский": ["Женский", None],
        "Ваш возраст?": ["18-25", "26-35", None],
        "Вы согласны?": ["Полностью согласен", "Скорее согласен",
                         "Затрудняюсь ответить", "Скорее не согласен",
                         "Совсем не согласен"],
    }
    path = tmp_path / "qa.json"
    path.write_text(json.dumps(qa, ensure_ascii=False), encoding="utf-8")
    return path
