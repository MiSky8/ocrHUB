async function loadEngines() {
  const resp = await fetch("/engines");
  const data = await resp.json();
  const container = document.getElementById("engine-list");
  data.engines.forEach((name) => {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "engines";
    checkbox.value = name;
    label.appendChild(checkbox);
    label.append(` ${name}`);
    container.appendChild(label);
  });
}

function renderPage(page) {
  const pageDiv = document.createElement("div");
  pageDiv.className = "page";

  if (page.image_base64) {
    const wrap = document.createElement("div");
    wrap.className = "page-image-wrap";

    const img = document.createElement("img");
    img.src = `data:image/png;base64,${page.image_base64}`;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("box-overlay");

    img.addEventListener("load", () => {
      svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
      (page.boxes || []).forEach((box) => {
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", box.x0);
        rect.setAttribute("y", box.y0);
        rect.setAttribute("width", box.x1 - box.x0);
        rect.setAttribute("height", box.y1 - box.y0);
        rect.setAttribute("class", "box");
        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        title.textContent = box.text;
        rect.appendChild(title);
        svg.appendChild(rect);
      });
    });

    wrap.appendChild(img);
    wrap.appendChild(svg);
    pageDiv.appendChild(wrap);
  }

  const pre = document.createElement("pre");
  pre.textContent = page.text;
  pageDiv.appendChild(pre);

  return pageDiv;
}

async function runOcr(event) {
  event.preventDefault();
  const form = document.getElementById("ocr-form");
  const formData = new FormData(form);
  const resp = await fetch("/ocr", { method: "POST", body: formData });
  const data = await resp.json();

  const resultsDiv = document.getElementById("results");
  resultsDiv.innerHTML = "";
  data.results.forEach((result) => {
    const block = document.createElement("div");
    block.className = "engine-result";

    const heading = document.createElement("h3");
    heading.textContent = `${result.engine} (${result.elapsed_ms}ms)`;
    block.appendChild(heading);

    if (result.error) {
      const err = document.createElement("pre");
      err.textContent = result.error;
      block.appendChild(err);
    } else {
      (result.pages || []).forEach((page) => block.appendChild(renderPage(page)));
    }

    resultsDiv.appendChild(block);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadEngines();
  document.getElementById("ocr-form").addEventListener("submit", runOcr);
});
