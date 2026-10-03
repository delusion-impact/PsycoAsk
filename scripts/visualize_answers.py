import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from paths import CHARTS_DIR, GENERATED_JSON, ensure_dirs, stamped

# === НАСТРОЙКИ ===
INPUT_FILE = GENERATED_JSON  # Файл после генерации
OUTPUT_DIR = CHARTS_DIR
MAX_QUESTIONS = None  # None = все вопросы, или число для теста
FIG_WIDTH = 24  # Ширина листа в дюймах
BAR_HEIGHT = 0.6  # Толщина полосы ответа

# Палитра для категорийных ответов (до 10 уникальных цветов)
COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"
]

ensure_dirs()


def load_and_prepare(filepath):
    df = pd.read_json(filepath, orient='records')
    # Убираем служебные колонки
    exclude = {"ID", "Время создания"}
    cols = [c for c in df.columns if c not in exclude]
    if MAX_QUESTIONS:
        cols = cols[:MAX_QUESTIONS]
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


def plot_answer_heatmap(df):
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
    out_path = stamped(CHARTS_DIR / "answer_heatmap.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"✅ Тепловая карта сохранена: {out_path}")


if __name__ == "__main__":
    df = load_and_prepare(INPUT_FILE)
    plot_answer_heatmap(df)