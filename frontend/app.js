"use strict";

// Токен подставляет сервер при отдаче страницы: без него запросы /api/*
// отклоняются, поэтому любая страница в браузере не сможет запустить пайплайн.
const TOKEN = window.PSYCOASK_TOKEN || "";

const state = {
  step: 1,
  file: null,
  parsed: false,
  generated: false,
  busy: false,
  stamp: null,
  artifacts: [],
  resultsCategory: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

// === Обмен с API ===

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "X-PsycoAsk-Token": TOKEN,
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Ошибка ${response.status}`);
  }
  return payload;
}

const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

// Файлы открываются в Проводнике через /api/open: обычная ссылка не годится,
// токен в заголовке при навигации не передаётся, и страница приложения
// заменялась бы ответом сервера.

// === Уведомления ===

let toastTimer = null;

function notify(text, kind = "") {
  const box = $("#toast");
  box.textContent = text;
  box.className = `toast${kind ? ` is-${kind}` : ""}`;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, kind === "error" ? 6000 : 2800);
}

$("#toast").addEventListener("click", () => { $("#toast").hidden = true; });

function humanSize(bytes) {
  if (!bytes) return "0 КБ";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

// === Панели ===

// Есть ли уже файлы визуализации: от этого зависит и кнопка «Результаты» на
// шаге 3, и отметки пройденных шагов на экране результатов.
function hasVisualResults() {
  return state.artifacts.some((item) => item.category === "visualize");
}

function showPanel(name) {
  state.step = name;
  $$(".panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === String(name));
  });
  const order = ["1", "2", "3"];
  const current = order.indexOf(String(name));
  // На экране результатов ни один шаг не активен, но выполненными отмечены
  // только реально пройденные: после одной генерации «Визуализация» ещё не
  // завершена и зелёной быть не должна.
  const reached = current < 0
    ? (hasVisualResults() ? 3 : state.generated ? 2 : 1)
    : current;
  $$(".step").forEach((tab) => {
    const index = order.indexOf(tab.dataset.step);
    tab.classList.toggle("is-active", index === current);
    tab.classList.toggle("is-done", index < reached);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

const showStep = (number) => showPanel(number);
const showResults = () => showPanel("results");

$$(".step").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.disabled || state.busy) return;
    showStep(tab.dataset.step);
  });
});

$$("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => {
        state.resultsCategory = null;
        showStep(button.dataset.goto);
    });
});

// === Шаг 1: выгрузка ===

function renderInputs(inputs) {
  const list = $("#inputs");
  list.innerHTML = "";

  if (!inputs.length) {
    list.innerHTML = '<li class="empty" style="cursor:default">В папке data/input нет Excel-файлов — загрузите выгрузку</li>';
    return;
  }

  inputs.forEach((item) => {
    const row = document.createElement("li");
    row.className = item.name === state.file ? "is-selected" : "";
    row.innerHTML = `
      <span class="file-icon">📄</span>
      <span class="file-name"></span>
      <span class="file-meta">${humanSize(item.size)} · ${item.modified.replace("T", " ")}</span>`;
    row.querySelector(".file-name").textContent = item.name;
    row.addEventListener("click", () => selectFile(item.name));
    list.appendChild(row);
  });
}

function selectFile(name) {
  state.file = name;
  renderInputs(state.inputs);
  syncButtons();
}

async function refreshInputs() {
  const data = await api("/api/state");
  applyState(data.state);
}

function applyState(data) {
  state.inputs = data.inputs || [];
  state.parsed = Boolean(data.parsed);
  state.generated = Boolean(data.generated);
  if (data.stamp) state.stamp = data.stamp;
  $("#workspace-chip").textContent = data.workspace || "";
  $("#workspace-chip").title = data.workspace || "";
  renderInputs(state.inputs);

  // Единственная выгрузка выбирается сразу: иначе шаг 2 упирается в
  // неактивную кнопку и непонятно, что надо сделать.
  if (!state.file && state.inputs.length) {
    selectFile(state.inputs[0].name);
  }

  if (state.parsed && data.questions) {
    $("#parse-summary").textContent =
      `Словарь собран: вопросов — ${data.questions}, вариантов ответов — ${data.answers}. ` +
      "Генератор выбирает ответы из этого словаря.";
    renderQuestions(data.question_preview || []);
  }
  syncButtons();
}

function renderQuestions(items) {
  const box = $("#questions-box");
  const list = $("#questions-list");
  list.innerHTML = "";
  if (!items.length) { box.hidden = true; return; }
  box.hidden = false;
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "q-item";
    node.innerHTML = "<b></b><span></span>";
    node.querySelector("b").textContent = item.question;
    node.querySelector("span").textContent = item.options.join(" · ");
    list.appendChild(node);
  });
}

$("#upload").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  const form = new FormData();
  form.append("file", file, file.name);
  try {
    notify(`Загружаем ${file.name}…`);
    const data = await api("/api/upload", { method: "POST", body: form });
    state.inputs = data.inputs;
    renderInputs(state.inputs);
    selectFile(data.name);
    notify(`Загружено: ${data.name}`, "ok");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    event.target.value = "";
  }
});

$("#workspace-chip").addEventListener("click", async () => {
  try {
    await post("/api/open?path=", {});
  } catch (error) {
    notify(error.message, "error");
  }
});

// === Шаг 2: количество анкет ===

const countInput = $("#count");
const countRange = $("#count-range");

function syncCount(value) {
  const parsed = Math.max(1, Math.min(1000, Number(value) || 1));
  countInput.value = parsed;
  countRange.value = Math.min(parsed, 1000);
}

countInput.addEventListener("input", () => { countRange.value = Math.min(Number(countInput.value) || 1, 1000); });
countInput.addEventListener("change", () => syncCount(countInput.value));
countRange.addEventListener("input", () => syncCount(countRange.value));

$$("[data-count]").forEach((button) => {
  button.addEventListener("click", () => syncCount(button.dataset.count));
});

$("#to-2").addEventListener("click", () => showStep(2));

// === Шаг 3: визуализация ===

["#opt-charts", "#opt-reports"].forEach((selector) => {
  $(selector).addEventListener("change", syncButtons);
});

// === Ход работы: текстовое поле в потоке страницы ===

function startTask(job, title) {
  state.busy = true;
  const box = $("#taskbox");
  box.hidden = false;
  $("#task-title").textContent = title;
  $("#task-bar").style.background = "";
  $("#task-log").textContent = "";
  syncButtons();
  return job;
}

function renderTask(job) {
  const pct = Math.round(job.progress * 100);
  $("#task-bar").style.width = `${pct}%`;
  $("#task-pct").textContent = `${pct}%`;
  $("#task-title").textContent = job.message || job.kind;
  const log = $("#task-log");
  log.textContent = job.log.slice(-12).join("\n");
  log.scrollTop = log.scrollHeight;
}

// Блок хода работы живёт только пока задача выполняется: после неё его
// скрываем, иначе он остаётся висеть поверх интерфейса.
function closeTask() {
  $("#taskbox").hidden = true;
  state.busy = false;
  syncButtons();
}

function waitFor(job, attempts = 0) {
  return api(`/api/jobs/${job.id}`).then(({ job: current }) => {
    renderTask(current);
    if (current.status === "done") return Promise.resolve(current);
    if (current.status === "failed") return Promise.reject(current);
    if (attempts > 4000) return Promise.reject({ error: "Задача выполняется слишком долго" });
    return new Promise((resolve) => {
      setTimeout(() => resolve(waitFor(job, attempts + 1)), 300);
    });
  });
}

// Состояния кнопок считает одна функция. Раньше обработчик чекбоксов
// перезаписывал disabled своими правилами и забывал про state.generated —
// кнопка «Построить» оставалась неактивной, пока чекбокс не трогали.
function syncButtons() {
  const hasInputs = Boolean(state.file);
  const wantsVisual = $("#opt-charts").checked || $("#opt-reports").checked;

  $("#run-generate").disabled = state.busy || !hasInputs;
  $("#run-visualize").disabled = state.busy || !state.generated || !wantsVisual;
  $("#to-2").disabled = !state.parsed && !hasInputs;
  $("#to-results-gen").disabled = state.busy || !state.generated;
  $("#to-results-viz").disabled = state.busy || !hasVisualResults();

  const generate = $("#run-generate");
  generate.textContent = hasInputs
    ? `Генерация анкет (${state.file})`
    : "Генерация анкет";
  if (!hasInputs) {
    generate.title = "Сначала выберите выгрузку на шаге 1";
  } else {
    generate.title = "";
  }

  const visualize = $("#run-visualize");
  if (!state.generated) {
    visualize.title = "Сначала выполните генерацию на шаге 2";
  } else if (!wantsVisual) {
    visualize.title = "Отметьте графики или отчёты";
  } else {
    visualize.title = "";
  }
}

// === Запуск шагов ===

$("#run-generate").addEventListener("click", async () => {
  if (!state.file) return;
  const count = Math.max(1, Math.min(1000, Number(countInput.value) || 1));
  try {
    const { job } = await post("/api/parse", { file: state.file });
    startTask(job, "Разбор выгрузки");
    await waitFor(job);

    const next = await post("/api/generate", { count });
    startTask(next.job, "Генерация анкет");
    const done = await waitFor(next.job);

    closeTask();
    notify(`Сгенерировано анкет: ${done.result.count}`, "ok");
    await refreshState();
    showStep(2);
  } catch (error) {
    $("#task-bar").style.background = "var(--err)";
    closeTask();
    notify(error.error || error.message, "error");
  }
});

$("#run-visualize").addEventListener("click", async () => {
  try {
    const { job } = await post("/api/visualize", {
      charts: $("#opt-charts").checked,
      reports: $("#opt-reports").checked,
    });
    startTask(job, "Визуализация");
    const done = await waitFor(job);

    closeTask();
    notify("Визуализация завершена", "ok");
    await refreshState();
    state.resultsCategory = "visualize";
    renderResults();
    showResults();
  } catch (error) {
    $("#task-bar").style.background = "var(--err)";
    closeTask();
    notify(error.error || error.message, "error");
  }
});

async function refreshState() {
  try {
    const data = await api("/api/state");
    applyState(data.state);
    if (data.state.stamp) state.stamp = data.state.stamp;
    state.artifacts = data.state.artifacts || [];
  } catch (error) {
    notify(error.message, "error");
  }
}

// === Результаты ===

const RESULTS_TITLES = {
  generate: "Результаты генерации",
  visualize: "Результаты визуализации",
};

function resultsHeader() {
  return RESULTS_TITLES[state.resultsCategory] || "Готово — файлы прогона";
}

function renderResults() {
  const header = $('[data-panel="results"] h2');
  if (header) header.textContent = resultsHeader();

  $("#result-summary").textContent = state.stamp
    ? `Файлы прогона ${state.stamp} — все в рабочей папке.`
    : "Файлы этого прогона — с одинаковым штампом в имени.";

  let items = state.artifacts;
  if (state.resultsCategory) {
    items = items.filter((item) => item.category === state.resultsCategory);
  }

  const list = $("#artifacts");
  list.innerHTML = "";
  if (!items.length) {
    const label = state.resultsCategory === "generate" ? "генерации"
      : state.resultsCategory === "visualize" ? "визуализации" : "прогона";
    list.innerHTML = `<li class="empty" style="cursor:default">Файлы ${label} пока нет</li>`;
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("li");
    row.innerHTML = `
      <span class="kind"></span>
      <span class="file-name"></span>
      <span class="file-meta">${item.modified ? item.modified.replace("T", " ") : ""}</span>
      <span class="file-meta">${humanSize(item.size)}</span>
      <button class="btn btn-secondary file-open">Открыть</button>`;
    row.querySelector(".kind").textContent = item.kind;
    row.querySelector(".file-name").textContent = item.name;

    const open = row.querySelector(".file-open");
    open.addEventListener("click", async () => {
      open.disabled = true;
      try {
        await post(`/api/open?path=${encodeURIComponent(item.path)}`, {});
      } catch (error) {
        notify(error.message, "error");
      } finally {
        open.disabled = false;
      }
    });
    list.appendChild(row);
  });
}

$("#to-results-gen").addEventListener("click", async () => {
  if (state.busy) return;
  await refreshState();
  state.resultsCategory = "generate";
  renderResults();
  showResults();
});

$("#to-results-viz").addEventListener("click", async () => {
  if (state.busy) return;
  await refreshState();
  state.resultsCategory = "visualize";
  renderResults();
  showResults();
});

$("#open-folder").addEventListener("click", async () => {
  try {
    await post("/api/open?path=output", {});
  } catch (error) {
    notify(error.message, "error");
  }
});

// === Старт ===

(async function start() {
  try {
    await refreshInputs();
  } catch (error) {
    notify(error.message, "error");
  }
})();