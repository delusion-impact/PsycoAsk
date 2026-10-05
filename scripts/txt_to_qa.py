"""Импорт словаря вопросов из текстового источника (data/input/ref_txt.txt).

Текстовый файл состоит из блоков «Тест 0» … «Тест 4». Каждый блок описывает
набор вопросов и вариантов ответов в своём формате:

  Тест 0 — «N. Вопрос», ниже строками варианты ответа.
  Тест 1 — заголовок «ответы на вопросы:» и общий список вариантов, далее
           пары «номер» / «вопрос».
  Тест 2 — «N. -» и строки «А) …», «Б) …»; все вопросы получают одно имя
           с суффиксами _2, _3…
  Тест 3 — «Ответы:» и список вариантов, далее пары «номер» / «вопрос».
  Тест 4 — «Ответы:» со строками «1 – Да», далее пары «номер» / «вопрос».

Результат — qa.json того же вида, что раньше собирал prepare_qa:
словарь «вопрос → варианты ответа» (None — не выбранный вариант).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from paths import INPUT_DIR, QA_JSON, ensure_dirs

TEST2_PREFIX = "Выберите утверждение, которое больше про вас:"


def _clean_option(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[-–—]\s*", "", text)  # буллет "- вариант"
    text = re.sub(r"^[АБAB]\)\s*", "", text)  # «А) вариант» в Тесте 2
    return text.strip()


def _split_blocks(text: str) -> dict[str, list[str]]:
    """Разбивает файл на блоки по заголовкам «Тест N»."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^Тест\s+(\d+)", line.strip(), re.IGNORECASE)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line.rstrip())
    return blocks


def _nonempty(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _dedupe(options: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for option in options:
        option = option.strip()
        if option and option not in seen:
            seen.add(option)
            result.append(option)
    return result


def parse_test0(lines: list[str]) -> dict[str, list[str]]:
    """«1. Вопрос» + строки вариантов ответа до пустой строки."""
    qa: dict[str, list[str]] = {}
    question = None
    options: list[str] = []

    def flush():
        if question is None:
            return
        if question == "Ваш пол":
            # Вопрос о поле в выгрузке разбит на два столбца:
            # «Ваш пол / Мужской» и «Ваш пол / Женский»
            for option in options:
                qa[f"Ваш пол / {option}"] = [None, option]
        else:
            qa[question] = _dedupe(options)

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            question, options = None, []
            continue
        match = re.match(r"^\d+\.\s*(.+)$", line)
        if match:
            flush()
            question, options = match.group(1).strip(), []
        elif question is not None:
            options.append(_clean_option(line))
    flush()
    return qa


def _parse_numbered_questions(lines: list[str]) -> list[str]:
    """Пары «номер» / «вопрос» в Тестах 1, 3, 4."""
    questions: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        # Вариант «1. Вопрос» в одной строке
        inline = re.match(r"^\d+[.)\t]\s*(.+)$", line)
        if inline and not re.fullmatch(r"\d+", inline.group(1).strip()):
            questions.append(inline.group(1).strip())
            index += 1
            continue
        if re.fullmatch(r"\d+", line) and index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if candidate and not re.fullmatch(r"\d+", candidate):
                questions.append(candidate)
                index += 2
                continue
        index += 1
    return questions


def parse_test1(lines: list[str]) -> dict[str, list[str]]:
    """Общий список ответов после «ответы на вопросы», далее вопросы."""
    qa: dict[str, list[str]] = {}
    options: list[str] = []
    body: list[str] = []
    in_answers = False
    for raw in lines:
        line = raw.strip()
        if not in_answers and "ответы на вопросы" in line.lower():
            in_answers = True
            continue
        if in_answers and not body:
            if not line:
                if options:
                    in_answers = False
                continue
            if re.fullmatch(r"\d+", line):
                in_answers = False
                body.append(line)
            else:
                options.append(_clean_option(line))
        elif line:
            body.append(line)

    for question in _parse_numbered_questions(body):
        key = question.rstrip(".")
        qa[key] = _dedupe(options)
    return qa


def parse_test2(lines: list[str]) -> dict[str, list[str]]:
    """«N. -» + «А) …», «Б) …»: один вопрос с суффиксами _2, _3…"""
    qa: dict[str, list[str]] = {}
    options: list[str] = []
    counter = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\d+\.\s*-", line):
            if options:
                qa[TEST2_PREFIX if counter == 0 else f"{TEST2_PREFIX}_{counter + 1}"] = _dedupe(options)
                counter += 1
            options = []
        elif re.match(r"^[АБAB]\)", line):
            options.append(_clean_option(line).rstrip("."))
    if options:
        qa[TEST2_PREFIX if counter == 0 else f"{TEST2_PREFIX}_{counter + 1}"] = _dedupe(options)
    return qa


def parse_test3(lines: list[str]) -> dict[str, list[str]]:
    """«Ответы:» + список вариантов, далее пары «номер» / «вопрос»."""
    qa: dict[str, list[str]] = {}
    options: list[str] = []
    body: list[str] = []
    after_answers = False
    for raw in lines:
        line = raw.strip()
        if not after_answers and line.lower().startswith("ответы"):
            continue
        if not after_answers:
            if not line:
                if options:
                    after_answers = True
                continue
            if re.fullmatch(r"\d+", line):
                after_answers = True
                body.append(line)
            else:
                options.append(_clean_option(line))
        elif line:
            body.append(line)

    for question in _parse_numbered_questions(body):
        qa[question] = _dedupe(options)
    return qa


def parse_test4(lines: list[str]) -> dict[str, list[str]]:
    """«Ответы:» + «1 – Да», далее пары «номер» / «вопрос»."""
    qa: dict[str, list[str]] = {}
    options: list[str] = []
    body: list[str] = []
    after_answers = False
    for raw in lines:
        line = raw.strip()
        if not after_answers and line.lower().startswith("ответы"):
            continue
        if not after_answers:
            if not line:
                if options:
                    after_answers = True
                continue
            match = re.match(r"^\d+\s*[–—-]\s*(.+)$", line)
            if match:
                options.append(match.group(1).strip())
            elif line == "№" or re.fullmatch(r"\d+", line):
                after_answers = True
                if re.fullmatch(r"\d+", line):
                    body.append(line)
            else:
                options.append(_clean_option(line))
        elif line:
            body.append(line)

    for question in _parse_numbered_questions(body):
        qa[question] = _dedupe(options)
    return qa


def build_qa(source) -> dict[str, list]:
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    blocks = _split_blocks(path.read_text(encoding="utf-8"))

    qa: dict[str, list] = {}
    parsers = {"0": parse_test0, "1": parse_test1, "2": parse_test2,
               "3": parse_test3, "4": parse_test4}
    for name, parser in parsers.items():
        if name in blocks:
            qa.update(parser(blocks[name]))
    if not qa:
        raise ValueError(f"В файле не найдено вопросов: {path}")
    return qa


def import_qa(source, output=None) -> dict[str, list]:
    qa = build_qa(source)
    out_path = Path(output) if output else Path(QA_JSON)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(qa, handle, ensure_ascii=False, indent=2)
    print(f"✅ Словарь вопросов собран: {out_path} ({len(qa)} вопросов)")
    return qa


if __name__ == "__main__":
    ensure_dirs()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT_DIR / "ref_txt.txt"
    import_qa(source)
