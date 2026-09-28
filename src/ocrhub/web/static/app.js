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

async function runOcr(event) {
  event.preventDefault();
  const form = document.getElementById("ocr-form");
  const formData = new FormData(form);
  const resp = await fetch("/ocr", { method: "POST", body: formData });
  const data = await resp.json();

  const resultsDiv = document.getElementById("results");
  resultsDiv.innerHTML = "";
  data.results.forEach((result) => {
    const block = document.createElement("pre");
    block.textContent = `[${result.engine}] (${result.elapsed_ms}ms)\n${result.error || result.text}`;
    resultsDiv.appendChild(block);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadEngines();
  document.getElementById("ocr-form").addEventListener("submit", runOcr);
});
