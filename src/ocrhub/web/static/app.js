const ENGINE_COLORS = {
  tesseract: "#1f5fa8",
  surya: "#b04a06",
  paddleocr: "#6b3fa0",
  datalab: "#2f7d4f",
  "ollama-deepseek": "#a7a195",
};

const state = {
  engines: [],
  selected: new Set(),
  file: null,
};

async function loadEngines() {
  const resp = await fetch("/engines");
  const data = await resp.json();
  state.engines = data.engines;
  renderEngineList();
}

function renderEngineList() {
  // NOTE: `.engine-row` is a <div>, not a <button> — Task 4 adds a second,
  // separate "Compare" <button> inside this row once that engine has a
  // result, and HTML forbids nesting <button> inside <button>. The row's
  // own select/deselect behavior lives on `.engine-select-btn` below.
  const container = document.getElementById("engine-list");
  container.innerHTML = "";
  state.engines.forEach((name) => {
    const row = document.createElement("div");
    row.className = "engine-row";

    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "engine-select-btn";
    selectBtn.setAttribute("aria-pressed", state.selected.has(name));

    const box = document.createElement("div");
    box.className = "engine-checkbox";
    box.style.setProperty("--_engine-color", ENGINE_COLORS[name] || "#999");
    box.style.background = state.selected.has(name) ? (ENGINE_COLORS[name] || "#999") : "transparent";

    const label = document.createElement("span");
    label.textContent = name;

    selectBtn.appendChild(box);
    selectBtn.appendChild(label);
    selectBtn.addEventListener("click", () => toggleEngine(name));
    row.appendChild(selectBtn);
    container.appendChild(row);
  });
}

function toggleEngine(name) {
  if (state.selected.has(name)) {
    state.selected.delete(name);
  } else {
    state.selected.add(name);
  }
  renderEngineList();
}

function handleFileChosen(file) {
  state.file = file;
  const chip = document.getElementById("file-chip");
  const nameEl = document.getElementById("file-name");
  chip.hidden = false;
  nameEl.textContent = file.name;
}

document.addEventListener("DOMContentLoaded", () => {
  loadEngines();
  document.getElementById("file-input").addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileChosen(e.target.files[0]);
  });
});
