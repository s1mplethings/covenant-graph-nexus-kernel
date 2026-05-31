// src/ui/forms.js

export function readFilters(dom) {
  const streamer = dom.querySelector("#filterStreamer").value.trim();
  const game = dom.querySelector("#filterGame").value.trim();
  const category = dom.querySelector("#filterCategory").value.trim();
  const minScore = parseFloat(dom.querySelector("#filterScore").value) || 0;

  return { streamer, game, category, minScore };
}

export function readManualMarker(form) {
  const streamer = form.querySelector("[name='streamer']").value.trim();
  const game = form.querySelector("[name='game']").value.trim();
  const category = form.querySelector("[name='category']").value.trim();
  const timestamp = form.querySelector("[name='timestamp']").value.trim();
  const time = form.querySelector("[name='time']").value.trim();
  const intensity = parseFloat(form.querySelector("[name='intensity']").value) || 0;
  const chatRate = parseFloat(form.querySelector("[name='chatRate']").value) || 0;
  const keywords = form.querySelector("[name='keywords']").value.trim().split(",").map(k => k.trim());
  const title = form.querySelector("[name='title']").value.trim();
  const description = form.querySelector("[name='description']").value.trim();

  return { streamer, game, category, timestamp, time, intensity, chatRate, keywords, title, description };
}

export function bindDom(dom, handlers) {
  const importButton = dom.querySelector("#import-button");
  const filterForm = dom.querySelector("#filter-form");
  const manualForm = dom.querySelector("#manual-form");
  const exportButton = dom.querySelector("#export-button");

  if (importButton) {
    importButton.addEventListener("click", handlers.onImport);
  }

  if (filterForm) {
    filterForm.addEventListener("submit", (event) => {
      event.preventDefault();
      handlers.onFilter(readFilters(filterForm));
    });
  }

  if (manualForm) {
    manualForm.addEventListener("submit", (event) => {
      event.preventDefault();
      handlers.onManualMarker(readManualMarker(manualForm));
    });
  }

  if (exportButton) {
    exportButton.addEventListener("click", handlers.onExport);
  }
}

export function setupForms(domIds) {
  const dom = {};
  domIds.forEach(id => {
    dom[id] = document.getElementById(id);
  });
  return dom;
}