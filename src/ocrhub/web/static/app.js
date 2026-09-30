const ENGINE_COLORS = {
  tesseract: "#1f5fa8",
  surya: "#b04a06",
  paddleocr: "#6b3fa0",
  datalab: "#2f7d4f",
  "ollama-deepseek": "#a7a195",
};

const PDF_ONLY = new Set(["pdfplumber"]);

const state = {
  engines: [],
  selected: new Set(),   // engines to RUN
  file: null,
  results: {},
  visible: new Set(),    // engines whose results are SHOWN
  showOriginal: true,
  originalUrl: null,
};
state.layoutMode = "side-by-side";
state.detectionsTab = null;
state.running = new Set();
let runTimer = null;

function isPdfFile() {
  return !!state.file && (state.file.type === "application/pdf" || /\.pdf$/i.test(state.file.name));
}

function engineDisabledReason(name) {
  return PDF_ONLY.has(name) && state.file && !isPdfFile() ? "PDF only" : "";
}

async function loadEngines() {
  const resp = await fetch("/engines");
  const data = await resp.json();
  state.engines = data.engines;
  renderEngineList();
}

function renderEngineList() {
  const container = document.getElementById("engine-list");
  container.innerHTML = "";
  state.engines.forEach((name) => {
    const reason = engineDisabledReason(name);
    const row = document.createElement("div");
    row.className = "engine-row" + (reason ? " disabled" : "");

    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "engine-select-btn";
    selectBtn.disabled = !!reason;
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

    if (reason) {
      const note = document.createElement("span");
      note.className = "engine-note";
      note.textContent = reason;
      row.appendChild(note);
    }
    container.appendChild(row);
  });
}

// Sidebar "Results" list: which finished results are shown in the main area.
function renderResultsList() {
  const section = document.getElementById("results-section");
  const list = document.getElementById("results-list");
  list.innerHTML = "";
  const names = state.engines.filter((n) => state.results[n]);
  section.hidden = !state.file;
  if (!state.file) return;

  const addRow = (label, color, meta, isOn, onToggle, isError) => {
    const row = document.createElement("div");
    row.className = "result-row" + (isError ? " failed" : "");
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "view-toggle" + (isOn ? " on" : "");
    toggle.textContent = isError ? "Failed" : isOn ? "On" : "Off";
    toggle.disabled = !!isError;
    toggle.setAttribute("aria-pressed", !!isOn);
    toggle.setAttribute("aria-label", `Show ${label}`);
    if (!isError) toggle.addEventListener("click", onToggle);
    const text = document.createElement("div");
    text.className = "result-text";
    const title = document.createElement("div");
    title.className = "result-title";
    if (color) title.appendChild(colorDot(label, 9));
    title.appendChild(document.createTextNode(label));
    const sub = document.createElement("div");
    sub.className = "result-meta";
    sub.textContent = meta;
    sub.title = meta;
    text.appendChild(title);
    text.appendChild(sub);
    row.appendChild(toggle);
    row.appendChild(text);
    list.appendChild(row);
  };

  addRow("Original", false, state.file.name, state.showOriginal, () => {
    state.showOriginal = !state.showOriginal;
    renderResultsGrid();
  }, false);

  names.forEach((name) => {
    const r = state.results[name];
    if (!r.ok) {
      addRow(name, true, r.error || "Failed", false, null, true);
      return;
    }
    const boxes = r.pages.length ? r.pages[0].boxes.length : 0;
    const meta = isTextOnly(r) ? `text only · ${r.elapsed_ms} ms` : `${boxes} boxes · ${r.elapsed_ms} ms`;
    addRow(name, true, meta, state.visible.has(name), () => toggleVisible(name), false);
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
  if (state.selected.size === 0) { setRunStatus("Tick at least one engine to run.", true); return; }
  const btn = document.getElementById("run-all-btn");
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Running…";
  setRunStatus("", false);
  const startedAt = Date.now();
  state.running = new Set(state.selected);
  const tick = () => {
    const secs = Math.round((Date.now() - startedAt) / 1000);
    setRunStatus(`Running ${Array.from(state.running).join(", ")}… ${secs}s`, false);
  };
  tick();
  renderResultsGrid();
  runTimer = setInterval(tick, 1000);
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
    data.results.forEach((r) => {
      state.results[r.engine] = r;
      if (r.ok) state.visible.add(r.engine); else state.visible.delete(r.engine);
    });
    setRunStatus("", false);
  } catch (e) {
    setRunStatus(e && e.message ? e.message : "Request failed.", true);
  } finally {
    clearInterval(runTimer);
    state.running = new Set();
    renderResultsGrid();
    btn.disabled = false;
    btn.textContent = label;
  }
}

function toggleVisible(name) {
  if (state.visible.has(name)) state.visible.delete(name); else state.visible.add(name);
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

function renderRunningCard(name) {
  const card = document.createElement("div");
  card.className = "engine-panel running-card";
  const header = document.createElement("div");
  header.className = "panel-header";
  header.appendChild(colorDot(name, 10));
  header.appendChild(document.createTextNode(` ${name}`));
  const body = document.createElement("div");
  body.className = "running-body";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  body.appendChild(spinner);
  body.appendChild(document.createTextNode(" Running…"));
  card.appendChild(header);
  card.appendChild(body);
  return card;
}

function originalSrc() {
  if (state.originalUrl) return state.originalUrl;
  // PDFs: borrow the first page image any finished engine rendered.
  for (const n of state.engines) {
    const r = state.results[n];
    if (r && r.ok && r.pages.length && r.pages[0].image_base64) return `data:image/png;base64,${r.pages[0].image_base64}`;
  }
  return null;
}

function renderOriginalPanel() {
  const panel = document.createElement("section");
  panel.className = "engine-panel";
  const header = document.createElement("div");
  header.className = "panel-header";
  const nameEl = document.createElement("span");
  nameEl.style.cssText = "font-size:14px;font-weight:600;";
  nameEl.textContent = "Original";
  const stats = document.createElement("div");
  stats.className = "panel-stats mono";
  stats.textContent = state.file ? state.file.name : "";
  header.appendChild(nameEl);
  header.appendChild(stats);
  panel.appendChild(header);

  const src = originalSrc();
  if (!src) {
    const note = document.createElement("div");
    note.className = "panel-note";
    note.textContent = "Preview appears once an engine that renders pages has run.";
    panel.appendChild(note);
    return panel;
  }
  const wrap = document.createElement("div");
  wrap.className = "page-image-wrap";
  const img = document.createElement("img");
  img.src = src;
  img.alt = "Original page";
  wrap.appendChild(img);
  panel.appendChild(wrap);
  return panel;
}

function renderResultsGrid() {
  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";
  renderResultsList();

  const shown = state.engines.filter((n) => state.visible.has(n) && state.results[n] && !state.running.has(n));
  const running = state.engines.filter((n) => state.running.has(n));
  const hasResults = Object.keys(state.results).length > 0;

  if (state.layoutMode === "overlay") {
    grid.className = "results-block";
    const names = shown.filter((n) => state.results[n].ok);
    if (names.length > 0) grid.appendChild(renderOverlayPanel(names));
  } else {
    grid.className = "results-row";
    if (state.file && state.showOriginal) grid.appendChild(renderOriginalPanel());
    running.forEach((name) => grid.appendChild(renderRunningCard(name)));
    shown.forEach((name) => grid.appendChild(renderPanel(name, state.results[name])));
  }

  if (grid.children.length === 0 || (state.layoutMode !== "overlay" && !state.file)) {
    grid.innerHTML = "";
    grid.className = "results-block";
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = !state.file
      ? "Upload an image or PDF, tick the engines to run, then press Run selected."
      : hasResults
        ? "Nothing is shown. Turn a result On in the Results list."
        : "Tick the engines to run, then press Run selected. Slow engines such as Surya can take a minute or more.";
    grid.appendChild(empty);
  }
  renderDetections();
}

function colorDot(name, size) {
  const dot = document.createElement("span");
  dot.style.cssText = `display:inline-block;width:${size}px;height:${size}px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"}`;
  return dot;
}

function renderDetections() {
  const tabsEl = document.getElementById("detections-tabs");
  const rowsEl = document.getElementById("detections-rows");
  tabsEl.innerHTML = "";
  rowsEl.innerHTML = "";

  const names = state.engines.filter((n) => state.visible.has(n) && state.results[n] && state.results[n].ok && !state.running.has(n));
  if (names.length === 0) return;
  if (!state.detectionsTab || !names.includes(state.detectionsTab)) {
    state.detectionsTab = names[0];
  }

  names.forEach((name) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "detections-tab" + (name === state.detectionsTab ? " active" : "");
    tab.appendChild(colorDot(name, 9));
    tab.appendChild(document.createTextNode(` ${name}`));
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
  let rows;
  if (isTextOnly(state.results[state.detectionsTab])) {
    // No boxes: list the scraped text lines in the order they were read.
    rows = [];
    pages.forEach((p) => {
      p.text.split("\n").filter((t) => t.trim()).forEach((t) => {
        rows.push({ text: t, reading_order: rows.length + 1, confidence: null });
      });
    });
  } else {
    const allOrdered = page.boxes.length > 0 && page.boxes.every((b) => b.reading_order !== null && b.reading_order !== undefined);
    rows = allOrdered
      ? [...page.boxes].sort((a, b) => a.reading_order - b.reading_order)
      : page.boxes;
  }

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
    bbox.textContent = Number.isFinite(box.x0)
      ? `${Math.round(box.x0)}, ${Math.round(box.y0)}, ${Math.round(box.x1 - box.x0)}, ${Math.round(box.y1 - box.y0)}`
      : "–";

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
    chip.appendChild(colorDot(name, 10));
    chip.appendChild(document.createTextNode(name));
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

// Engines such as pdfplumber read a PDF's text layer: text, but no boxes or page image.
function isTextOnly(result) {
  return result.pages.length > 0 && result.pages.every((p) => !p.image_base64 && p.boxes.length === 0);
}

function renderTextBody(result) {
  const body = document.createElement("div");
  body.className = "text-body";
  result.pages.forEach((p) => {
    if (result.pages.length > 1) {
      const h = document.createElement("div");
      h.className = "text-page-label mono";
      h.textContent = `Page ${p.page_number}`;
      body.appendChild(h);
    }
    const pre = document.createElement("pre");
    pre.textContent = p.text || "(no text found)";
    body.appendChild(pre);
  });
  return body;
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
  if (isTextOnly(result)) {
    const stats = document.createElement("div");
    stats.className = "panel-stats mono";
    stats.textContent = `${result.pages.length} page${result.pages.length === 1 ? "" : "s"} · text only · ${result.elapsed_ms} ms`;
    header.appendChild(stats);
    panel.appendChild(header);
    panel.appendChild(renderTextBody(result));
    return panel;
  }
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
  wrap.className = "page-image-wrap ocr-only";
  if (!page.image_base64) {
    // No page image (e.g. datalab): draw on a blank page sized to the boxes.
    if (!page.boxes.length) return wrap;
    const w = Math.max(...page.boxes.map((b) => b.x1)) + Math.min(...page.boxes.map((b) => b.x0));
    const h = Math.max(...page.boxes.map((b) => b.y1)) + Math.min(...page.boxes.map((b) => b.y0));
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("blank-page");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    drawBoxes(svg, page.boxes, ENGINE_COLORS[engineName] || "#999", true);
    wrap.appendChild(svg);
    return wrap;
  }

  const img = document.createElement("img");
  img.src = `data:image/png;base64,${page.image_base64}`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("box-overlay");

  img.addEventListener("load", () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    drawBoxes(svg, page.boxes, ENGINE_COLORS[engineName] || "#999", true);
  });

  wrap.appendChild(img);
  wrap.appendChild(svg);
  return wrap;
}

// inPlace: draw the OCR text at each box's position on a blank page (the
// page image is hidden), instead of a small label under the box.
function drawBoxes(svg, boxes, color, inPlace = false) {
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

    if (state.show.text && inPlace) {
      const w = Math.max(box.x1 - box.x0, 1);
      const h = box.y1 - box.y0;
      const n = (box.text || "").length;
      // Largest font where the text, wrapped to the box width, fits its height
      // (average glyph is ~0.6em wide, lines are 1.25em tall).
      let f = Math.max(h * 0.85, 6);
      let lines = Math.ceil((n * 0.6 * f) / w);
      while (lines > 1 && f > 6 && lines * f * 1.25 > h) {
        f -= 1;
        lines = Math.ceil((n * 0.6 * f) / w);
      }
      if (lines <= 1) {
        const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
        t.setAttribute("x", box.x0);
        t.setAttribute("y", box.y1 - h * 0.2);
        t.setAttribute("font-size", f);
        t.setAttribute("textLength", w);
        t.setAttribute("lengthAdjust", "spacingAndGlyphs");
        t.setAttribute("fill", "#111");
        t.setAttribute("font-family", "system-ui, sans-serif");
        t.textContent = box.text;
        g.appendChild(t);
      } else {
        const fo = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
        fo.setAttribute("x", box.x0);
        fo.setAttribute("y", box.y0);
        fo.setAttribute("width", w);
        fo.setAttribute("height", h);
        const div = document.createElement("div");
        div.style.cssText = `font:${f}px/1.25 system-ui,sans-serif;color:#111;overflow:hidden;height:${h}px;overflow-wrap:anywhere;`;
        div.textContent = box.text;
        fo.appendChild(div);
        g.appendChild(fo);
      }
    } else if (state.show.text) {
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
  if (state.originalUrl) URL.revokeObjectURL(state.originalUrl);
  state.file = file;
  state.originalUrl = file.type && file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
  const chip = document.getElementById("file-chip");
  const nameEl = document.getElementById("file-name");
  chip.hidden = false;
  nameEl.textContent = file.name;
  state.results = {};
  state.visible.clear();
  state.showOriginal = true;
  state.detectionsTab = null;
  state.engines.forEach((n) => { if (engineDisabledReason(n)) state.selected.delete(n); });
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
  renderResultsGrid();
  document.getElementById("file-input").addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileChosen(e.target.files[0]);
  });
  document.getElementById("run-all-btn").addEventListener("click", () => runAll());
});
