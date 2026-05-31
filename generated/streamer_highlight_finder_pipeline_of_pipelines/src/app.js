// src/app.js
import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { parseRecordsFromText, normalizeRecord } from './core/importer.js';
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
const recordsContainer = document.getElementById('records-container');
const statusSummary = document.getElementById('status-summary');

// Application State
let records = [];
let filteredRecords = [];

// Load data from localStorage on page load
window.addEventListener('load', () => {
  try {
    records = loadFromLocalStorage() || [];
    filteredRecords = [...records];
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } catch (error) {
    renderError('Failed to load data from localStorage.', recordsContainer);
  }
});

// Import data from file or textarea
importButton.addEventListener('click', () => {
  const file = fileInput.files[0];
  const textareaContent = jsonTextarea.value.trim();

  if (file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsedRecords = parseRecordsFromText(event.target.result).map(normalizeRecord);
        records = records.concat(parsedRecords.map(scoreRecord));
        records = sortRecords(records);
        filteredRecords = [...records];
        saveToLocalStorage(records);
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, statusSummary);
      } catch (error) {
        renderError('Failed to parse file content.', recordsContainer);
      }
    };
    reader.readAsText(file);
  } else if (textareaContent) {
    try {
      const parsedRecords = parseRecordsFromText(textareaContent).map(normalizeRecord);
      records = records.concat(parsedRecords.map(scoreRecord));
      records = sortRecords(records);
      filteredRecords = [...records];
      saveToLocalStorage(records);
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, statusSummary);
    } catch (error) {
      renderError('Failed to parse textarea content.', recordsContainer);
    }
  } else {
    renderError('No input provided for import.', recordsContainer);
  }
});

// Apply filters
filterForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const filters = readFilters(filterForm);
  filteredRecords = applyFilters(records, filters);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
});

// Add manual highlight
manualForm.addEventListener('submit', (event) => {
  event.preventDefault();
  try {
    const manualRecord = readManualMarker(manualForm);
    const scoredRecord = scoreRecord(normalizeRecord(manualRecord));
    records.push(scoredRecord);
    records = sortRecords(records);
    filteredRecords = applyFilters(records, readFilters(filterForm));
    saveToLocalStorage(records);
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } catch (error) {
    renderError('Failed to add manual highlight.', recordsContainer);
  }
});

// Export filtered records
exportButton.addEventListener('click', () => {
  try {
    exportData(filteredRecords, 'filtered_highlights.json');
  } catch (error) {
    renderError('Failed to export data.', recordsContainer);
  }
});