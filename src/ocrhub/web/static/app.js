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
  results: {},
  compare: new Set(),
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

    if (state.results[name]) {
      const compareBtn = document.createElement("button");
      compareBtn.type = "button";
      compareBtn.className = "compare-toggle-btn" + (state.compare.has(name) ? " active" : "");
      compareBtn.textContent = "Compare";
      compareBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleCompare(name); });
      row.appendChild(compareBtn);
    }

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

async function runAll() {
  if (!state.file || state.selected.size === 0) return;
  const formData = new FormData();
  formData.append("file", state.file);
  state.selected.forEach((name) => formData.append("engines", name));

  const resp = await fetch("/ocr", { method: "POST", body: formData });
  const data = await resp.json();
  data.results.forEach((r) => { state.results[r.engine] = r; });
  renderEngineList();
  renderResultsGrid();
}

function toggleCompare(name) {
  if (state.compare.has(name)) {
    state.compare.delete(name);
  } else if (state.compare.size < 3) {
    state.compare.add(name);
  }
  renderResultsGrid();
}

function renderResultsGrid() {
  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";
  grid.style.display = "grid";
  grid.style.gap = "16px";
  const names = Array.from(state.compare);
  grid.style.gridTemplateColumns = `repeat(${Math.max(1, names.length)}, minmax(0, 1fr))`;

  names.forEach((name) => {
    const result = state.results[name];
    if (!result) return;
    grid.appendChild(renderPanel(name, result));
  });
}

function renderPanel(name, result) {
  const panel = document.createElement("section");
  panel.className = "engine-panel";

  const header = document.createElement("div");
  header.className = "panel-header";
  const dot = document.createElement("span");
  dot.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"};margin-right:6px;`;
  const nameEl = document.createElement("span");
  nameEl.style.cssText = "font-size:14px;font-weight:600;";
  nameEl.textContent = name;
  header.appendChild(dot);
  header.appendChild(nameEl);

  if (!result.ok) {
    const err = document.createElement("pre");
    err.textContent = result.error;
    panel.appendChild(header);
    panel.appendChild(err);
    return panel;
  }

  const page = result.pages[0];
  const stats = document.createElement("div");
  stats.className = "panel-stats mono";
  const conf = page.confidence != null ? Math.round(page.confidence <= 1 ? page.confidence * 100 : page.confidence) + "%" : "–";
  stats.textContent = `${page.boxes.length} boxes · ${conf} conf · ${result.elapsed_ms} ms`;
  header.appendChild(stats);
  panel.appendChild(header);

  panel.appendChild(renderPageWithBoxes(page, name));
  return panel;
}

function renderPageWithBoxes(page, engineName) {
  const wrap = document.createElement("div");
  wrap.className = "page-image-wrap";
  if (!page.image_base64) return wrap;

  const img = document.createElement("img");
  img.src = `data:image/png;base64,${page.image_base64}`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("box-overlay");

  img.addEventListener("load", () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    drawBoxes(svg, page.boxes, ENGINE_COLORS[engineName] || "#999");
  });

  wrap.appendChild(img);
  wrap.appendChild(svg);
  return wrap;
}

function drawBoxes(svg, boxes, color) {
  if (!state.show.boxes && !state.show.text && !state.show.orderNumbers) return;
  boxes.forEach((box) => {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");

    if (state.show.boxes) {
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", box.x0);
      rect.setAttribute("y", box.y0);
      rect.setAttribute("width", box.x1 - box.x0);
      rect.setAttribute("height", box.y1 - box.y0);
      rect.setAttribute("fill", color + "22");
      rect.setAttribute("stroke", color);
      rect.setAttribute("stroke-width", "1.5");
      g.appendChild(rect);
    }

    if (state.show.text) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
      label.setAttribute("x", box.x0 - 1);
      label.setAttribute("y", box.y1 + 1);
      label.setAttribute("width", Math.max(box.x1 - box.x0 + 40, 20));
      label.setAttribute("height", 14);
      const div = document.createElement("div");
      div.className = "mono";
      div.style.cssText = `background:${color};color:#fff;font-size:9px;line-height:12px;padding:0 3px;display:inline-block;white-space:nowrap;`;
      div.textContent = box.text;
      label.appendChild(div);
      g.appendChild(label);
    }

    if (state.show.orderNumbers && box.reading_order !== null && box.reading_order !== undefined) {
      const badge = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
      badge.setAttribute("x", box.x0 - 8);
      badge.setAttribute("y", box.y0 - 8);
      badge.setAttribute("width", 15);
      badge.setAttribute("height", 15);
      const div = document.createElement("div");
      div.className = "mono box-order-badge";
      div.style.borderColor = color;
      div.textContent = box.reading_order;
      badge.appendChild(div);
      g.appendChild(badge);
    }

    svg.appendChild(g);
  });
}

function handleFileChosen(file) {
  state.file = file;
  const chip = document.getElementById("file-chip");
  const nameEl = document.getElementById("file-name");
  chip.hidden = false;
  nameEl.textContent = file.name;
}

document.addEventListener("DOMContentLoaded", () => {
  state.show = { boxes: true, text: true, orderNumbers: true };
  loadEngines();
  document.getElementById("file-input").addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileChosen(e.target.files[0]);
  });
  document.getElementById("run-all-btn").addEventListener("click", () => runAll());
});
