// src/ui/forms.js

export function readFilters(dom) {
  const streamer = dom.querySelector("#filterStreamer")?.value || "";
  const game = dom.querySelector("#filterGame")?.value || "";
  const category = dom.querySelector("#filterCategory")?.value || "";
  const minScore = parseFloat(dom.querySelector("#filterScore")?.value) || 0;

  return { streamer, game, category, minScore };
}

export function readManualMarker(form) {
  const streamer = form.querySelector("[name='streamer']")?.value || "";
  const game = form.querySelector("[name='game']")?.value || "";
  const category = form.querySelector("[name='category']")?.value || "";
  const timestamp = form.querySelector("[name='timestamp']")?.value || "";
  const time = parseInt(form.querySelector("[name='time']")?.value, 10) || 0;
  const intensity = parseInt(form.querySelector("[name='intensity']")?.value, 10) || 0;
  const chatRate = parseInt(form.querySelector("[name='chatRate']")?.value, 10) || 0;
  const keywords = (form.querySelector("[name='keywords']")?.value || "").split(",").map(k => k.trim());
  const title = form.querySelector("[name='title']")?.value || "";
  const description = form.querySelector("[name='description']")?.value || "";

  return { streamer, game, category, timestamp, time, intensity, chatRate, keywords, title, description };
}

export function bindDom(dom, handlers) {
  const filterForm = dom.querySelector("#filter-form");
  const manualForm = dom.querySelector("#manual-form");
  const importButton = dom.querySelector("#import-button");
  const exportButton = dom.querySelector("#export-button");

  if (filterForm && handlers.onFilterSubmit) {
    filterForm.addEventListener("submit", (e) => {
      e.preventDefault();
      handlers.onFilterSubmit(readFilters(dom));
    });
  }

  if (manualForm && handlers.onManualSubmit) {
    manualForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const newRecord = readManualMarker(manualForm);
      handlers.onManualSubmit(newRecord);
    });
  }

  if (importButton && handlers.onImport) {
    importButton.addEventListener("click", handlers.onImport);
  }

  if (exportButton && handlers.onExport) {
    exportButton.addEventListener("click", handlers.onExport);
  }
}

export function setupForms(domIds) {
  const dom = {};
  for (const [key, id] of Object.entries(domIds)) {
    dom[key] = document.getElementById(id);
  }
  return dom;
}