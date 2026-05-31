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
  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const importedRecords = importData(event.target.result);
        records = importedRecords.map(normalizeRecord).map(scoreRecord);
        records = sortRecords(records);
        filteredRecords = [...records];
        saveToLocalStorage(records);
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, statusSummary);
      } catch (error) {
        renderError('Failed to import data. Please check the file format.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (jsonTextarea.value.trim()) {
    try {
      const importedRecords = parseRecordsFromText(jsonTextarea.value.trim());
      records = importedRecords.map(normalizeRecord).map(scoreRecord);
      records = sortRecords(records);
      filteredRecords = [...records];
      saveToLocalStorage(records);
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, statusSummary);
    } catch (error) {
      renderError('Failed to import data. Please check the JSON format.', recordsContainer);
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
    newRecord.score = scoreRecord(newRecord).score;
    records.push(newRecord);
    records = sortRecords(records);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    saveToLocalStorage(records);
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } else {
    renderError('Failed to add manual marker. Please check the input fields.', recordsContainer);
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
function initializeApp() {
  records = loadFromLocalStorage() || [];
  filteredRecords = [...records];
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

initializeApp();