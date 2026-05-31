// src/ui/forms.js

export function readFilters(dom) {
  const streamer = dom.querySelector('#filterStreamer')?.value || '';
  const game = dom.querySelector('#filterGame')?.value || '';
  const category = dom.querySelector('#filterCategory')?.value || '';
  const minScore = parseFloat(dom.querySelector('#filterScore')?.value) || 0;

  return { streamer, game, category, minScore };
}

export function readManualMarker(form) {
  const streamer = form.querySelector('#manualStreamer')?.value || '';
  const game = form.querySelector('#manualGame')?.value || '';
  const category = form.querySelector('#manualCategory')?.value || '';
  const timestamp = form.querySelector('#manualTimestamp')?.value || '';
  const time = form.querySelector('#manualTime')?.value || '';
  const intensity = parseFloat(form.querySelector('#manualIntensity')?.value) || 0;
  const chatRate = parseFloat(form.querySelector('#manualChatRate')?.value) || 0;
  const keywords = (form.querySelector('#manualKeywords')?.value || '').split(',').map(k => k.trim());
  const title = form.querySelector('#manualTitle')?.value || '';
  const description = form.querySelector('#manualDescription')?.value || '';

  return { streamer, game, category, timestamp, time, intensity, chatRate, keywords, title, description };
}

export function bindDom(dom, handlers) {
  const filterForm = dom.querySelector('#filter-form');
  const manualForm = dom.querySelector('#manual-form');
  const exportButton = dom.querySelector('#export-button');

  if (filterForm) {
    filterForm.addEventListener('submit', (event) => {
      event.preventDefault();
      handlers.onFilterSubmit(readFilters(dom));
    });
  }

  if (manualForm) {
    manualForm.addEventListener('submit', (event) => {
      event.preventDefault();
      handlers.onManualSubmit(readManualMarker(manualForm));
    });
  }

  if (exportButton) {
    exportButton.addEventListener('click', (event) => {
      event.preventDefault();
      handlers.onExport();
    });
  }
}

export function setupForms(domIds) {
  const dom = {};
  for (const [key, id] of Object.entries(domIds)) {
    dom[key] = document.getElementById(id);
  }
  return dom;
}