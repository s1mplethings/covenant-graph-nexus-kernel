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
function handleImport(data) {
  try {
    const importedRecords = importData(data).map(scoreRecord);
    records = sortRecords([...records, ...importedRecords]);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    saveToLocalStorage(records);
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } catch (error) {
    renderError('Failed to import data. Please check the format.', recordsContainer);
  }
}

function handleFileImport(event) {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = (e) => handleImport(e.target.result);
    reader.readAsText(file);
  }
}

function handleTextareaImport() {
  const data = jsonTextarea.value;
  handleImport(data);
}

function handleFilterChange() {
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleManualSubmit(event) {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  records.push(scoreRecord(newRecord));
  records = sortRecords(records);
  filteredRecords = applyFilters(records, readFilters(filterForm));
  saveToLocalStorage(records);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleExport() {
  exportData(filteredRecords, 'filtered_highlights.json');
}

// Event Listeners
fileInput.addEventListener('change', handleFileImport);
importButton.addEventListener('click', handleTextareaImport);
filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  handleFilterChange();
});
filterForm.addEventListener('input', handleFilterChange);
manualForm.addEventListener('submit', handleManualSubmit);
exportButton.addEventListener('click', handleExport);

// Initialization
function initializeApp() {
  records = loadFromLocalStorage().map(scoreRecord);
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

initializeApp();