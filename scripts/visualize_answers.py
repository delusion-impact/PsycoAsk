from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

from paths import CHARTS_DIR, GENERATED_JSON, ensure_dirs, stamped

# === НАСТРОЙКИ ===
INPUT_FILE = GENERATED_JSON  # Файл после генерации
OUTPUT_DIR = CHARTS_DIR
MAX_QUESTIONS = None  # None = все вопросы, или число для теста
FIG_WIDTH = 24  # Ширина листа в дюймах
BAR_HEIGHT = 0.6  # Толщина полосы ответа

# Палитра для категориальных ответов (до 10 уникальных цветов)
COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"
]


def load_and_prepare(filepath, max_questions=None):
    limit = MAX_QUESTIONS if max_questions is None else max_questions
    df = pd.read_json(filepath, orient='records')
    # Убираем служебные колонки
    exclude = {"ID", "Время создания"}
    cols = [c for c in df.columns if c not in exclude]
    if limit:
        cols = cols[:limit]
    return df[cols]


def build_legend(answer_to_color):
    """Создает список патчей для легенды"""
    patches = []
    for answer, color in sorted(answer_to_color.items(), key=lambda x: str(x[0])):
        label = str(answer) if answer is not None else "(пусто)"
        # Обрезаем длинные ответы в легенде
        if len(label) > 40:
            label = label[:37] + "..."
        patches.append(mpatches.Patch(color=color, label=label))
    return patches


def plot_answer_heatmap(df, output=None, show=True):
    """Строит 100 %-ную диаграмму по всем вопросам и возвращает путь к PNG.

    show=False нужен графическому приложению: без него matplotlib открыл бы
    окно и блокировал фоновый поток задачи.
    """
    n_questions = len(df.columns)

    # Определяем глобальную палитру: маппинг ответ -> цвет
    all_answers = set()
    for col in df.columns:
        all_answers.update(df[col].dropna().unique())
    all_answers.add(None)  # Для пустых значений

    answer_list = sorted(all_answers, key=str)
    answer_to_color = {ans: COLORS[i % len(COLORS)] for i, ans in enumerate(answer_list)}

    # Создаем фигуру. Высота зависит от количества вопросов
    fig_height = max(8, n_questions * 0.45 + 3)
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, fig_height))

    y_positions = list(range(n_questions))

    for idx, col in enumerate(df.columns):
        counts = df[col].value_counts(normalize=True, dropna=False)

        left = 0
        for answer, freq in counts.items():
            color = answer_to_color.get(answer, "#CCCCCC")
            ax.barh(
                y=idx, width=freq, left=left, height=BAR_HEIGHT,
                color=color, edgecolor="white", linewidth=0.5
            )
            # Подпись процента внутри бара, если он достаточно широкий
            if freq > 0.07:
                ax.text(
                    left + freq / 2, idx, f"{freq:.0%}",
                    ha='center', va='center', fontsize=7,
                    color='white', fontweight='bold'
                )
            left += freq

    # Настройка осей
    ax.set_yticks(y_positions)
    labels = [str(c)[:80] + "..." if len(str(c)) > 80 else str(c) for c in df.columns]
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()  # Первый вопрос сверху

    ax.set_xlim(0, 1)
    ax.set_xlabel("Доля ответов", fontsize=11)
    ax.set_title(f"Распределение ответов ({len(df)} записей × {n_questions} вопросов)",
                 fontsize=14, pad=15)

    # Легенда справа
    legend_patches = build_legend(answer_to_color)
    ax.legend(
        handles=legend_patches,
        loc='upper left', bbox_to_anchor=(1.01, 1),
        fontsize=8, title="Варианты ответов",
        title_fontsize=10, frameon=True
    )

    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(axis='x', labelsize=9)

    plt.tight_layout()
    out_path = Path(output) if output else stamped(Path(OUTPUT_DIR) / "answer_heatmap.png")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    if show:
        plt.show()
    plt.close(fig)
    print(f"✅ Тепловая карта сохранена: {out_path}")
    return out_path


def build_heatmap(source=None, output=None, show=True):
    """Тепловая карта ответов: файл после генерации → PNG."""
    ensure_dirs()
    df = load_and_prepare(source or INPUT_FILE)
    return plot_answer_heatmap(df, output=output, show=show)


if __name__ == "__main__":
    ensure_dirs()
    df = load_and_prepare(INPUT_FILE)
    plot_answer_heatmap(df)