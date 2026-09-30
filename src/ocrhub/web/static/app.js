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
state.layoutMode = "side-by-side";
state.detectionsTab = null;

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

function setRunStatus(msg, isError) {
  const el = document.getElementById("run-status");
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
}

async function runAll() {
  if (!state.file) { setRunStatus("Choose a file first.", true); return; }
  if (state.selected.size === 0) { setRunStatus("Select at least one engine.", true); return; }
  const btn = document.getElementById("run-all-btn");
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Running…";
  setRunStatus("", false);
  try {
    const formData = new FormData();
    formData.append("file", state.file);
    state.selected.forEach((name) => formData.append("engines", name));

    const resp = await fetch("/ocr", { method: "POST", body: formData });
    if (!resp.ok) {
      let detail = "";
      try { detail = (await resp.json()).detail || ""; } catch (e) { /* non-JSON body */ }
      throw new Error(`Request failed (${resp.status})${typeof detail === "string" && detail ? ": " + detail : ""}`);
    }
    let data;
    try { data = await resp.json(); } catch (e) { throw new Error("Server returned a non-JSON response."); }
    data.results.forEach((r) => { state.results[r.engine] = r; });
    renderEngineList();
    renderResultsGrid();
  } catch (e) {
    setRunStatus(e && e.message ? e.message : "Request failed.", true);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

function toggleCompare(name) {
  if (state.compare.has(name)) {
    state.compare.delete(name);
  } else if (state.compare.size < 3) {
    state.compare.add(name);
  }
  renderResultsGrid();
}

function setLayoutMode(mode) {
  state.layoutMode = mode;
  document.getElementById("mode-side-by-side").classList.toggle("active", mode === "side-by-side");
  document.getElementById("mode-overlay").classList.toggle("active", mode === "overlay");
  renderResultsGrid();
}

function toggleShow(key) {
  state.show[key] = !state.show[key];
  document.getElementById(`toggle-${key === "orderNumbers" ? "order" : key}`).classList.toggle("active", state.show[key]);
  renderResultsGrid();
}

function renderResultsGrid() {
  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";
  const allNames = Array.from(state.compare);

  if (allNames.length > 0) {
    if (state.layoutMode === "side-by-side") {
      grid.style.display = "grid";
      grid.style.gap = "16px";
      grid.style.gridTemplateColumns = `repeat(${allNames.length}, minmax(0, 1fr))`;
      allNames.forEach((name) => {
        const result = state.results[name];
        if (!result) return;
        grid.appendChild(renderPanel(name, result));
      });
    } else {
      const names = allNames.filter((n) => state.results[n] && state.results[n].ok);
      if (names.length > 0) {
        grid.style.display = "block";
        grid.appendChild(renderOverlayPanel(names));
      }
    }
  }
  renderDetections();
}

function renderDetections() {
  const tabsEl = document.getElementById("detections-tabs");
  const rowsEl = document.getElementById("detections-rows");
  tabsEl.innerHTML = "";
  rowsEl.innerHTML = "";

  const names = Array.from(state.compare).filter((n) => state.results[n] && state.results[n].ok);
  if (names.length === 0) return;
  if (!state.detectionsTab || !names.includes(state.detectionsTab)) {
    state.detectionsTab = names[0];
  }

  names.forEach((name) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "detections-tab" + (name === state.detectionsTab ? " active" : "");
    const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"}"></span>`;
    tab.innerHTML = `${dot} ${name}`;
    tab.addEventListener("click", () => { state.detectionsTab = name; renderDetections(); });
    tabsEl.appendChild(tab);
  });

  const pages = state.results[state.detectionsTab].pages;
  if (!pages.length) {
    const note = document.createElement("div");
    note.className = "panel-note";
    note.textContent = "No pages.";
    rowsEl.appendChild(note);
    return;
  }
  const page = pages[0];
  const allOrdered = page.boxes.length > 0 && page.boxes.every((b) => b.reading_order !== null && b.reading_order !== undefined);
  const rows = allOrdered
    ? [...page.boxes].sort((a, b) => a.reading_order - b.reading_order)
    : page.boxes;

  rows.forEach((box, i) => {
    const row = document.createElement("div");
    row.className = "detections-row";
    row.style.background = i % 2 ? "var(--row-alt)" : "#fff";

    const order = document.createElement("div");
    order.style.fontWeight = "600";
    order.textContent = box.reading_order !== null && box.reading_order !== undefined ? box.reading_order : "–";

    const text = document.createElement("div");
    text.style.cssText = "white-space:normal;overflow-wrap:anywhere;";
    text.textContent = box.text;
    text.title = box.text;

    const conf = document.createElement("div");
    if (box.confidence !== null && box.confidence !== undefined) {
      const pct = Math.round(box.confidence);
      const barWrap = document.createElement("div");
      barWrap.style.cssText = "display:flex;align-items:center;gap:8px;";
      const bar = document.createElement("div");
      bar.className = "conf-bar";
      const fill = document.createElement("div");
      fill.className = "conf-bar-fill";
      fill.style.width = Math.round(34 * (pct / 100)) + "px";
      fill.style.background = pct >= 70 ? "var(--success)" : "var(--warn)";
      bar.appendChild(fill);
      barWrap.appendChild(bar);
      const span = document.createElement("span");
      span.textContent = pct + "%";
      barWrap.appendChild(span);
      conf.appendChild(barWrap);
    } else {
      conf.textContent = "–";
    }

    const bbox = document.createElement("div");
    bbox.style.color = "var(--muted-2)";
    bbox.textContent = `${Math.round(box.x0)}, ${Math.round(box.y0)}, ${Math.round(box.x1 - box.x0)}, ${Math.round(box.y1 - box.y0)}`;

    row.appendChild(order);
    row.appendChild(text);
    row.appendChild(conf);
    row.appendChild(bbox);
    rowsEl.appendChild(row);
  });
}

function renderOverlayPanel(names) {
  const panel = document.createElement("section");
  panel.className = "engine-panel";

  const header = document.createElement("div");
  header.className = "panel-header";
  names.forEach((name) => {
    const chip = document.createElement("span");
    chip.style.cssText = `display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;margin-right:12px;`;
    chip.innerHTML = `<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"}"></span>${name}`;
    header.appendChild(chip);
  });
  panel.appendChild(header);

  // Canonical image: first engine (in `names` order) whose first page has an image.
  const canonicalName = names.find((n) => state.results[n].pages.length && state.results[n].pages[0].image_base64);
  if (!canonicalName) return panel;
  const canonicalPage = state.results[canonicalName].pages[0];

  const wrap = document.createElement("div");
  wrap.className = "page-image-wrap";
  const img = document.createElement("img");
  img.src = `data:image/png;base64,${canonicalPage.image_base64}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("box-overlay");

  img.addEventListener("load", () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    const canonicalW = img.naturalWidth, canonicalH = img.naturalHeight;

    names.forEach((name) => {
      if (!state.results[name].pages.length) return;
      const page = state.results[name].pages[0];
      let scaleX = 1, scaleY = 1;
      if (page.image_base64 && name !== canonicalName) {
        // Measure this engine's own image dimensions before scaling its boxes.
        const probe = new Image();
        probe.onload = () => {
          scaleX = canonicalW / probe.naturalWidth;
          scaleY = canonicalH / probe.naturalHeight;
          drawBoxes(svg, scaleBoxes(page.boxes, scaleX, scaleY), ENGINE_COLORS[name] || "#999");
        };
        probe.src = `data:image/png;base64,${page.image_base64}`;
      } else {
        drawBoxes(svg, page.boxes, ENGINE_COLORS[name] || "#999");
      }
    });
  });

  wrap.appendChild(img);
  wrap.appendChild(svg);
  panel.appendChild(wrap);
  return panel;
}

function scaleBoxes(boxes, scaleX, scaleY) {
  return boxes.map((b) => ({
    ...b,
    x0: b.x0 * scaleX, y0: b.y0 * scaleY, x1: b.x1 * scaleX, y1: b.y1 * scaleY,
  }));
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

  if (!result.pages.length) {
    panel.appendChild(header);
    const note = document.createElement("div");
    note.className = "panel-note";
    note.textContent = "No pages.";
    panel.appendChild(note);
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
  state.results = {};
  state.compare.clear();
  state.detectionsTab = null;
  setRunStatus("", false);
  renderEngineList();
  renderResultsGrid();
}

document.addEventListener("DOMContentLoaded", () => {
  state.show = { boxes: true, text: true, orderNumbers: true };

  document.getElementById("mode-side-by-side").addEventListener("click", () => setLayoutMode("side-by-side"));
  document.getElementById("mode-overlay").addEventListener("click", () => setLayoutMode("overlay"));
  document.getElementById("toggle-boxes").addEventListener("click", () => toggleShow("boxes"));
  document.getElementById("toggle-text").addEventListener("click", () => toggleShow("text"));
  document.getElementById("toggle-order").addEventListener("click", () => toggleShow("orderNumbers"));

  loadEngines();
  document.getElementById("file-input").addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileChosen(e.target.files[0]);
  });
  document.getElementById("run-all-btn").addEventListener("click", () => runAll());
});
