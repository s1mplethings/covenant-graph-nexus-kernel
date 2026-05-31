// app.js
import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { parseRecordsFromText, normalizeRecord, importData } from './core/importer.js';
import { downloadJson, exportData } from './core/exporter.js';
import { loadRecords, saveRecords, clearRecords, loadFromLocalStorage, saveToLocalStorage } from './state/store.js';
import { renderRecords, renderSummary, renderError } from './ui/render.js';
import { readFilters, readManualMarker } from './ui/forms.js';

// DOM Elements
const fileInput = document.getElementById('file-input');
const jsonTextarea = document.getElementById('json-textarea');
const importButton = document.getElementById('import-button');
const filterForm = document.getElementById('filter-form');
const manualForm = document.getElementById('manual-form');
const exportButton = document.getElementById('export-button');
const statusSummary = document.getElementById('status-summary');
const recordsContainer = document.getElementById('records-container');

// State
let records = [];
let filteredRecords = [];

// Functions
function handleImport() {
  const file = fileInput.files[0];
  const textData = jsonTextarea.value;

  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const importedRecords = importData(event.target.result);
        processRecords(importedRecords);
      } catch (error) {
        renderError('Failed to import file data.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (textData) {
    try {
      const importedRecords = importData(textData);
      processRecords(importedRecords);
    } catch (error) {
      renderError('Failed to import textarea data.', recordsContainer);
    }
  } else {
    renderError('No data provided for import.', recordsContainer);
  }
}

function processRecords(importedRecords) {
  records = importedRecords.map(normalizeRecord).map(scoreRecord);
  records = sortRecords(records);
  saveRecords(records);
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleFilter() {
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleManualMarker(event) {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  if (newRecord) {
    records.push(scoreRecord(normalizeRecord(newRecord)));
    records = sortRecords(records);
    saveRecords(records);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } else {
    renderError('Failed to add manual marker.', recordsContainer);
  }
}

function handleExport() {
  exportData(filteredRecords, 'filtered_highlights.json');
}

function restoreState() {
  records = loadFromLocalStorage() || [];
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
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
restoreState();