// src/app.js

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
    const importedRecords = importData(data).map(normalizeRecord);
    records = importedRecords.map(record => ({
      ...record,
      score: scoreRecord(record),
    }));
    records = sortRecords(records);
    saveRecords(records);
    filteredRecords = records;
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  } catch (error) {
    renderError('Failed to import data. Please check the format.', recordsContainer);
  }
}

function handleFilters() {
  const filters = readFilters(filterForm);
  filteredRecords = applyFilters(records, filters);
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleManualMarker(event) {
  event.preventDefault();
  const newRecord = readManualMarker(manualForm);
  newRecord.score = scoreRecord(newRecord);
  records.push(newRecord);
  records = sortRecords(records);
  saveRecords(records);
  filteredRecords = applyFilters(records, readFilters(filterForm));
  renderRecords(filteredRecords, recordsContainer);
  renderSummary(records, filteredRecords, statusSummary);
}

function handleExport() {
  exportData(filteredRecords, 'filtered_highlights.json');
}

function restoreFromLocalStorage() {
  const storedRecords = loadFromLocalStorage();
  if (storedRecords) {
    records = storedRecords.map(record => ({
      ...record,
      score: scoreRecord(record),
    }));
    records = sortRecords(records);
    filteredRecords = records;
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, statusSummary);
  }
}

function saveToLocalStorageHandler() {
  saveToLocalStorage(records);
}

// Event Listeners
importButton.addEventListener('click', () => {
  const file = fileInput.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = () => handleImport(reader.result);
    reader.readAsText(file);
  } else if (jsonTextarea.value.trim()) {
    handleImport(jsonTextarea.value.trim());
  } else {
    renderError('No input provided. Please upload a file or paste JSON.', recordsContainer);
  }
});

filterForm.addEventListener('input', handleFilters);

manualForm.addEventListener('submit', handleManualMarker);

exportButton.addEventListener('click', handleExport);

window.addEventListener('beforeunload', saveToLocalStorageHandler);

// Initialization
restoreFromLocalStorage();