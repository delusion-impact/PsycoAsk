# AGENTS.md

## Проект

PsycoAsk: пайплайн обработки опроса (txt-структура вопросов → словарь `qa.json`
→ синтетические ответы → Excel-отчёты). Два интерфейса к одной логике:

- `python main.py` — гибридное приложение (локальный HTTP-сервер + pywebview/браузер),
  шаги в UI: «1 Выгрузка» (импорт `ref_txt.txt` → `txt_to_qa`) и «2 Генерация»
  (+ опция «создать отчёт Excel с data bars»).
- `python scripts/run_pipeline.py` — консольный запуск с вопросами (legacy:
  парсинг xlsx, PNG-шагов больше нет, только Excel-отчёты).

## Ключевая архитектура (неочевидно)

- Вся логика пайплайна живёт в `scripts/`. `app/bridge.py` импортирует скрипты и
  вызывает их функции напрямую — не дублируй логику в `app/`, меняй только в
  `scripts/`, иначе консоль и приложение разойдутся.
- `scripts/` загружается по именам файлов, а не как пакет: новый скрипт нужно
  перечислить **в двух местах** — `hiddenimports` в `build/psycoask.spec`
  (one-file) и в списке модулей `build/build.ps1` (`-AsFolder`), иначе сборка
  молча не подхватит его.
- `scripts/paths.py` читает `PSYCOASK_HOME` один раз при импорте и строит из него
  все пути. `app/config.py setup_workspace()` выставляет её до первого импорта
  `paths`. Если импортировать `paths` раньше — пути застынут.
- `PSYCOASK_STAMP` — общий штамп имён файлов на весь запуск `run_pipeline.py`;
  одиночный запуск скрипта получает свой. Промежуточные JSON штампа не имеют
  (фиксированные имена).
- Версия — `APP_VERSION` в `app/__init__.py`; имя exe берётся оттуда же:
  `dist\PsycoAsk-<версия>.exe`.

## Команды

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
python main.py --browser        # или --serve-only / --port 8750 / --no-open
python scripts/run_pipeline.py  # консоль, --yes без вопросов
python scripts/<имя>.py         # отдельный шаг, по порядку (см. README)
powershell -ExecutionPolicy Bypass -File .\build\build.ps1   # EXE; -AsFolder, -Clean
python -m pytest                # 49 тестов (pytest.ini, testpaths=tests)
```

- PowerShell здесь: нет `&&` (используй `;`), прямой запуск `.ps1` блокируется
  execution policy — только через `powershell -ExecutionPolicy Bypass -File`.
- Линтера и CI в репозитории нет. Тесты — pytest, автономная временная рабочая
  папка через `PSYCOASK_HOME` в `tests/conftest.py`; E2E — `tests/test_pipeline_smoke.py`.
- Перед сборкой убей зависшие процессы `PsycoAsk-*`: занятый `dist\*.exe` даёт
  `PermissionError [WinError 5]` в конце сборки.

## Подводные камни

- `frontend/` пакетируется в exe (`--add-data frontend;frontend`): правки
  `index.html`/`app.js` видны в сборке только после пересборки.
- Консоль Windows в cp1251: `UnicodeEncodeError` на эмодзи из print →
  `$env:PYTHONIOENCODING = "utf-8"`.
- `/api/*` требует заголовок `X-PsycoAsk-Token`; без него 403. Токен подставляется
  в HTML при отдаче, поэтому прямые ссылки без заголовка не работают — файлы
  открываются через `POST /api/open`.
- Задачи (`app/jobs.py`) выполняются строго по одной: шаги пишут в общие
  промежуточные файлы, параллельный запуск смешает прогоны.
- `app/server.py` дочитывает тело запроса до маршрутизации — не убирай это,
  иначе keep-alive-соединение ломается с «Ошибка 501».
- При `ModuleNotFoundError: No module named 'numpy._core...'` — venv собран под
  другую версию Python: `python -m pip install --force-reinstall --no-cache-dir -r requirements.txt`.
- PyInstaller-сборка не включает интерактивный `run_pipeline.py` — он только в
  исходниках.
- PNG/matplotlib/seaborn удалены из проекта: в `requirements.txt` только
  pandas/numpy/openpyxl (+pywebview необязательно).

## Настройки (в коде, а не в конфигах)

- Генерация: верх `scripts/generate_data.py` (`NUM_RECORDS`, `MAX_NUM_RECORDS`,
  `ID_MIN/MAX`, `DATE_START/DATE_END`, `MALE_KEY/FEMALE_KEY`).
- Наборы ответов на шаге 2 (радиокнопки в `frontend/index.html`) читают
  `data/input/MEMpreset.json`: имена профилей в `value` должны совпадать
  с ключами `presets` в файле (регистр не важен). Файл входит в сборку
  (`--add-data`/`datas`) и подсеивается в рабочую папку при старте
  (`app/config.py _seed_preset`); fallback-путь — в `generate_data._preset_path`.
- Визуализация: параметры стилей в `visualize_to_excel.py`
  (`visualize_to_excel_bars.py`).
- Автоподбор ширины столбцов выгрузки: `json_to_xlsx.py` (`MAX_COL_WIDTH`).

Подробности — в `README.md` (он актуален и является основным документом).
