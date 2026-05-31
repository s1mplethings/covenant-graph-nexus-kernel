export function readFilters(dom = document) {
  const streamer = dom.querySelector('#filterStreamer').value;
  const game = dom.querySelector('#filterGame').value;
  const category = dom.querySelector('#filterCategory').value;
  const minScore = Number(dom.querySelector('#filterScore').value || 0);

  return { streamer, game, category, minScore };
}

export function readManualMarker(form) {
  const value = (name) => form.querySelector(`#${name}, [name="${name}"]`)?.value || '';
  const streamer = value('streamer');
  const game = value('game');
  const category = value('category');
  const timestamp = value('timestamp');
  const time = value('time');
  const intensity = Number(value('intensity') || 5);
  const chatRate = Number(value('chatRate') || 20);
  const keywords = value('keywords').split(',').map((item) => item.trim()).filter(Boolean);
  const title = value('title');
  const description = value('description');

  return { streamer, game, category, timestamp, time, intensity, chatRate, keywords, title, description };
}

export function bindDom(dom, handlers) {
  const importButton = dom.querySelector('#import-button');
  const exportButton = dom.querySelector('#export-button');
  const filterForm = dom.querySelector('#filter-form');
  const manualForm = dom.querySelector('#manual-form');

  importButton.addEventListener('click', handlers.importData);
  exportButton.addEventListener('click', handlers.exportData);
  filterForm.addEventListener('submit', (event) => {
    event.preventDefault();
    handlers.applyFilters(readFilters(dom));
  });
  manualForm.addEventListener('submit', (event) => {
    event.preventDefault();
    handlers.addManualMarker(readManualMarker(manualForm));
  });
}

export function setupForms(domIds) {
  const forms = domIds.map(id => document.getElementById(id));
  forms.forEach(form => {
    form.reset();
  });
}
