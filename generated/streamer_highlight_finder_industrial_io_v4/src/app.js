// app.js
import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { parseRecordsFromText, normalizeRecord, importData } from './core/importer.js';
import { downloadJson, exportData } from './core/exporter.js';
import { loadRecords, saveRecords, loadFromLocalStorage, saveToLocalStorage } from './state/store.js';
import { renderRecords, renderSummary, renderError } from './ui/render.js';
import { readFilters, readManualMarker } from './ui/forms.js';

// DOM Elements
const fileInput = document.getElementById('file-input');
const jsonTextarea = document.getElementById('json-textarea');
const importButton = document.getElementById('import-button');
const filterForm = document.getElementById('filter-form');
const exportButton = document.getElementById('export-button');
const manualForm = document.getElementById('manual-form');
const statusSummary = document.getElementById('status-summary');
const recordsContainer = document.getElementById('records-container');

// State
let records = [];
let filteredRecords = [];

// Functions
function handleImport() {
  const file = fileInput.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const importedData = importData(event.target.result);
        records = importedData.map(normalizeRecord).map(scoreRecord);
        records = sortRecords(records);
        filteredRecords = records; // Default to all records
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, statusSummary);
        saveToLocalStorage(records);
      } catch (error) {
        renderError('Failed to import data.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (jsonTextarea.value.trim()) {
    try {
      const importedData = parseRecordsFromText(jsonTextarea.value);
      records = importedData.map(normalizeRecord).map(scoreRecord);
      records = sortRecords(records);
      filteredRecords = records; // Default to all records
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, statusSummary);
      saveToLocalStorage(records);
    } catch (error) {
      renderError('Failed to import data.', recordsContainer);
    }
  } else {
    renderError('No data provided for import.', recordsContainer);
  }
}

function handleFilter() {
  const filters = readFilters(filterForm);
  filteredRecords = applyFilters(records, filters);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleManualMarker(event) {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  if (newRecord) {
    records.push(scoreRecord(normalizeRecord(newRecord)));
    records = sortRecords(records);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
    saveToLocalStorage(records);
  } else {
    renderError('Failed to add manual marker.', recordsContainer);
  }
}

function handleExport() {
  exportData(filteredRecords, 'filtered_highlights.json');
}

// Event Listeners
importButton.addEventListener('click', handleImport);
filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  handleFilter();
});
manualForm.addEventListener('submit', handleManualMarker);
exportButton.addEventListener('click', handleExport);

// Initialization
window.addEventListener('load', () => {
  records = loadFromLocalStorage() || [];
  filteredRecords = records;
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
});