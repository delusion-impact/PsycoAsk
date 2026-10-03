from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from paths import CHARTS_DIR, GENERATED_JSON, SURVEY_JSON, ensure_dirs, stamped

# Настройка стиля и шрифтов для кириллицы
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False
sns.set_theme(style="whitegrid")

ORIGINAL_FILE = SURVEY_JSON  # Исходные данные из парсера
GENERATED_FILE = GENERATED_JSON  # Синтетические данные
OUTPUT_DIR = CHARTS_DIR

SERVICE_COLUMNS = {"ID", "Время создания"}
MALE_COLUMN = "Ваш пол / Мужской"
FEMALE_COLUMN = "Ваш пол / Женский"

TOP_QUESTIONS = 10
LIKERT_SCALE = [
    "Совсем не согласен",
    "Скорее не согласен",
    "Затрудняюсь ответить",
    "Скорее согласен",
    "Полностью согласен",
]
LIKERT_VALUES = {answer: rank for rank, answer in enumerate(LIKERT_SCALE, start=1)}

EMPTY_LABEL = "(пусто)"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path in (ORIGINAL_FILE, GENERATED_FILE):
        if not Path(path).exists():
            raise FileNotFoundError(f"Файл не найден: {path} — сначала выполните предыдущие шаги пайплайна")
    return (pd.read_json(ORIGINAL_FILE, orient='records'),
            pd.read_json(GENERATED_FILE, orient='records'))


def save_figure(fig, filename: str):
    out_path = stamped(Path(OUTPUT_DIR) / filename)
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()
    plt.close(fig)
    print(f"✅ Сохранено: {out_path}")


def label_of(value) -> str:
    """Единая подпись категории: пустые значения видно как '(пусто)'."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return EMPTY_LABEL
    return str(value).strip() or EMPTY_LABEL


def truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def plot_gender_balance(orig: pd.DataFrame, gen: pd.DataFrame):
    """Проверка баланса пола в оригинале и синтетике"""
    missing = [col for col in (MALE_COLUMN, FEMALE_COLUMN) if col not in orig.columns
               or col not in gen.columns]
    if missing:
        print(f"⚠️ Нет столбцов о поле ({', '.join(missing)}) — график баланса пола пропущен")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    counts_by_source = []

    for ax, df, title in zip(axes, [orig, gen], ["Оригинал", "Сгенерированные данные"]):
        male = int(df[MALE_COLUMN].notna().sum())
        female = int(df[FEMALE_COLUMN].notna().sum())
        counts_by_source.append(male + female)

        ax.bar(["Мужской", "Женский"], [male, female], color=["#4C72B0", "#DD8452"])
        ax.set_title(f"{title} (n={len(df)})")
        ax.set_ylabel("Количество")

        # Подписи значений
        for i, value in enumerate([male, female]):
            ax.text(i, value + 0.5, str(value), ha='center', fontweight='bold')

    if counts_by_source[0]:
        share = counts_by_source[1] / counts_by_source[0]
        if abs(share - 1) > 0.01:
            print(f"⚠️ Объём генерации отличается от оригинала: "
                  f"{counts_by_source[0]} против {counts_by_source[1]} записей")

    plt.tight_layout()
    save_figure(fig, "01_gender_balance.png")


def compare_categories(orig: pd.Series, gen: pd.Series) -> tuple[list[str], list[float], list[float]]:
    """Доли ответов по объединённому списку категорий: оригинал против генерации."""
    orig_counts = orig.map(label_of).value_counts(normalize=True)
    gen_counts = gen.map(label_of).value_counts(normalize=True)

    categories = sorted(set(orig_counts.index) | set(gen_counts.index))
    return (categories,
            [float(orig_counts.get(cat, 0.0)) for cat in categories],
            [float(gen_counts.get(cat, 0.0)) for cat in categories])


def plot_distributions_comparison(orig: pd.DataFrame, gen: pd.DataFrame, top_n: int = TOP_QUESTIONS):
    """Сравнение топ-N вопросов по количеству уникальных ответов"""
    # Вопросы, которые есть и в оригинале, и в генерации
    common = [col for col in orig.columns if col in gen.columns and col not in SERVICE_COLUMNS]
    if not common:
        print("⚠️ Нет общих вопросов между оригиналом и генерацией")
        return

    diversity = orig[common].nunique().sort_values(ascending=False).head(top_n).index.tolist()

    n_cols = 2
    n_rows = max(1, (len(diversity) + n_cols - 1) // n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(18, 5 * n_rows), squeeze=False)
    axes = axes.flatten()

    for idx, col in enumerate(diversity):
        ax = axes[idx]
        categories, orig_shares, gen_shares = compare_categories(orig[col], gen[col])

        x_pos = list(range(len(categories)))
        width = 0.35
        ax.bar([p - width / 2 for p in x_pos], orig_shares,
               width, label='Оригинал', alpha=0.8)
        ax.bar([p + width / 2 for p in x_pos], gen_shares,
               width, label='Генерация', alpha=0.8)

        ax.set_xticks(x_pos)
        ax.set_xticklabels([truncate(cat, 20) for cat in categories],
                           rotation=45, ha='right', fontsize=8)
        ax.set_title(truncate(col, 60), fontsize=10)
        ax.legend(fontsize=8)
        ax.set_ylabel("Доля ответов")

    # Убираем пустые подграфики
    for idx in range(len(diversity), len(axes)):
        axes[idx].set_visible(False)

    plt.tight_layout()
    save_figure(fig, "02_distributions_comparison.png")


def plot_likert_heatmap(df: pd.DataFrame, slug: str, title_suffix: str):
    """Тепловая карта корреляций для вопросов со шкалой Лайкерта"""
    likert_cols = [col for col in df.columns if not col in SERVICE_COLUMNS
                   and df[col].isin(LIKERT_SCALE).any()]
    if not likert_cols:
        print(f"⚠️ Не найдено столбцов со шкалой Лайкерта{title_suffix}")
        return

    # Числовое кодирование для корреляции
    numeric_df = df[likert_cols].replace(LIKERT_VALUES).apply(pd.to_numeric, errors='coerce')
    numeric_df = numeric_df.dropna(axis=1, how='all')

    if numeric_df.shape[1] < 2:
        print(f"⚠️ Для корреляции нужно минимум 2 вопроса{title_suffix}, найдено {numeric_df.shape[1]}")
        return

    corr = numeric_df.corr().dropna(how="all").dropna(axis=1, how="all")
    if corr.empty:
        print(f"⚠️ Не удалось посчитать корреляции{title_suffix}")
        return

    fig, ax = plt.subplots(figsize=(20, 16))
    sns.heatmap(corr, ax=ax, annot=False, cmap="RdBu_r", center=0,
                xticklabels=[truncate(col, 30) for col in corr.columns],
                yticklabels=[truncate(col, 30) for col in corr.index])
    ax.set_title(f"Корреляция ответов (шкала Лайкерта){title_suffix}", fontsize=14)
    plt.tight_layout()
    save_figure(fig, f"03_likert_correlation_{slug}.png")


if __name__ == "__main__":
    ensure_dirs()
    orig, gen = load_data()
    print(f"📊 Построение графиков: оригинал {len(orig)} записей, генерация {len(gen)} записей")

    plot_gender_balance(orig, gen)
    plot_distributions_comparison(orig, gen)
    plot_likert_heatmap(orig, "original", " — Оригинал")
    plot_likert_heatmap(gen, "generated", " — Генерация")

    print(f"\n🎉 Все графики сохранены в папке '{OUTPUT_DIR}/'")