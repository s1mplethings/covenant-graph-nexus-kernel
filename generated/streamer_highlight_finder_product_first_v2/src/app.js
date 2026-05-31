// app.js
import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { parseRecordsFromText, normalizeRecord, importData } from './core/importer.js';
import { downloadJson, exportData } from './core/exporter.js';
import { loadRecords, saveRecords, loadFromLocalStorage, saveToLocalStorage } from './state/store.js';
import { renderRecords, renderSummary, renderError } from './ui/render.js';
import { readFilters, readManualMarker } from './ui/forms.js';

// DOM elements
const fileInput = document.getElementById('file-input');
const jsonTextarea = document.getElementById('json-textarea');
const importButton = document.getElementById('import-button');
const filterForm = document.getElementById('filter-form');
const manualForm = document.getElementById('manual-form');
const exportButton = document.getElementById('export-button');
const statusSummary = document.getElementById('status-summary');
const recordsContainer = document.getElementById('records-container');

// Application state
let records = [];
let filteredRecords = [];

// Load records from localStorage on page load
window.addEventListener('load', () => {
  records = loadFromLocalStorage() || [];
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
});

// Import records from file or textarea
importButton.addEventListener('click', () => {
  const file = fileInput.files[0];
  const text = jsonTextarea.value;

  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const importedRecords = importData(event.target.result);
        records = records.concat(importedRecords.map(normalizeRecord));
        saveToLocalStorage(records);
        filteredRecords = applyFilters(records, readFilters(filterForm));
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, statusSummary);
      } catch (error) {
        renderError('Failed to import records.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (text) {
    try {
      const importedRecords = importData(text);
      records = records.concat(importedRecords.map(normalizeRecord));
      saveToLocalStorage(records);
      filteredRecords = applyFilters(records, readFilters(filterForm));
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, statusSummary);
    } catch (error) {
      renderError('Failed to import records.', recordsContainer);
    }
  } else {
    renderError('No input provided for import.', recordsContainer);
  }
});

// Apply filters
filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
});

// Add manual marker
manualForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  if (newRecord) {
    records.push(normalizeRecord(newRecord));
    saveToLocalStorage(records);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } else {
    renderError('Failed to add manual marker.', recordsContainer);
  }
});

// Export filtered records
exportButton.addEventListener('click', () => {
  exportData(filteredRecords, 'filtered_highlights.json');
});