// src/app.js
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
const recordsContainer = document.getElementById('records-container');

// Application state
let records = [];
let filteredRecords = [];

// Load records from localStorage on page load
window.addEventListener('load', () => {
  records = loadFromLocalStorage() || [];
  filteredRecords = records;
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, document.getElementById('status-summary'));
});

// Import data from file or textarea
importButton.addEventListener('click', () => {
  const file = fileInput.files[0];
  const textareaContent = jsonTextarea.value.trim();

  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const importedRecords = importData(event.target.result);
        records = importedRecords.map(normalizeRecord).map(scoreRecord);
        records = sortRecords(records);
        filteredRecords = records;
        saveToLocalStorage(records);
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, document.getElementById('status-summary'));
      } catch (error) {
        renderError('Failed to import data from file.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (textareaContent) {
    try {
      const importedRecords = parseRecordsFromText(textareaContent);
      records = importedRecords.map(normalizeRecord).map(scoreRecord);
      records = sortRecords(records);
      filteredRecords = records;
      saveToLocalStorage(records);
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, document.getElementById('status-summary'));
    } catch (error) {
      renderError('Failed to import data from textarea.', recordsContainer);
    }
  } else {
    renderError('No data provided for import.', recordsContainer);
  }
});

// Apply filters
filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const filters = readFilters(filterForm);
  filteredRecords = applyFilters(records, filters);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, document.getElementById('status-summary'));
});

// Add manual marker
manualForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  records.push(scoreRecord(normalizeRecord(newRecord)));
  records = sortRecords(records);
  filteredRecords = applyFilters(records, readFilters(filterForm));
  saveToLocalStorage(records);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, document.getElementById('status-summary'));
});

// Export filtered records
exportButton.addEventListener('click', () => {
  exportData(filteredRecords, 'filtered_highlights.json');
});