import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { importData } from './core/importer.js';
import { exportData } from './core/exporter.js';
import { loadRecords, saveRecords } from './state/store.js';
import { renderRecords, renderSummary, renderError } from './ui/render.js';
import { readFilters, readManualMarker } from './ui/forms.js';

const statusSummary = document.getElementById('status-summary');
const recordsContainer = document.getElementById('records-container');
const fileInput = document.getElementById('file-input');
const jsonTextarea = document.getElementById('json-textarea');
const importButton = document.getElementById('import-button');
const filterForm = document.getElementById('filter-form');
const exportButton = document.getElementById('export-button');
const manualForm = document.getElementById('manual-form');

let records = sortRecords(loadRecords().map(scoreRecord));
let filteredRecords = records;

function commitRecords(nextRecords) {
  records = sortRecords(nextRecords.map(scoreRecord));
  filteredRecords = records;
  saveRecords(records);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function applyCurrentFilters() {
  const filters = readFilters(document);
  filteredRecords = applyFilters(records, filters);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function importText(text) {
  const imported = importData(text);
  commitRecords(imported);
}

renderRecords(filteredRecords, recordsContainer);
renderSummary(records, filteredRecords, statusSummary);

fileInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.addEventListener('load', () => {
    try {
      importText(String(reader.result || ''));
    } catch (error) {
      renderError(error.message || 'Unable to import file', recordsContainer);
    }
  });
  reader.readAsText(file);
});

importButton.addEventListener('click', () => {
  try {
    importText(jsonTextarea.value);
  } catch (error) {
    renderError(error.message || 'Invalid JSON format', recordsContainer);
  }
});

filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  applyCurrentFilters();
});

filterForm.addEventListener('input', () => {
  applyCurrentFilters();
});

manualForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  commitRecords([...records, newRecord]);
});

exportButton.addEventListener('click', () => {
  exportData(filteredRecords.length ? filteredRecords : records, 'filtered_highlights.json');
});
