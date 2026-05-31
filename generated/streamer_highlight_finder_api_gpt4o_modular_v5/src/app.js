// src/app.js
import { scoreRecord, sortRecords } from './core/scoring.js';
import { applyFilters } from './core/filtering.js';
import { parseRecordsFromText, normalizeRecord, importData } from './core/importer.js';
import { downloadJson, exportData } from './core/exporter.js';
import { loadRecords, saveRecords, loadFromLocalStorage, saveToLocalStorage } from './state/store.js';
import { renderRecords, renderSummary, renderError } from './ui/render.js';
import { readFilters, readManualMarker } from './ui/forms.js';

document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const jsonTextarea = document.getElementById('json-textarea');
  const importButton = document.getElementById('import-button');
  const filterForm = document.getElementById('filter-form');
  const manualForm = document.getElementById('manual-form');
  const exportButton = document.getElementById('export-button');
  const recordsContainer = document.getElementById('records-container');

  let records = [];
  let filteredRecords = [];

  // Load records from localStorage on page load
  try {
    records = loadFromLocalStorage() || [];
    filteredRecords = [...records];
    renderRecords(filteredRecords, recordsContainer);
    renderSummary(records, filteredRecords, 'Data loaded from localStorage.');
  } catch (error) {
    renderError('Failed to load data from localStorage.', recordsContainer);
  }

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
          filteredRecords = [...records];
          saveToLocalStorage(records);
          renderRecords(filteredRecords, recordsContainer);
          renderSummary(records, filteredRecords, 'Data imported from file.');
        } catch (error) {
          renderError('Failed to import data from file.', recordsContainer);
        }
      };
      reader.readAsText(file);
    } else if (textareaContent) {
      try {
        const importedRecords = importData(textareaContent);
        records = importedRecords.map(normalizeRecord).map(scoreRecord);
        records = sortRecords(records);
        filteredRecords = [...records];
        saveToLocalStorage(records);
        renderRecords(filteredRecords, recordsContainer);
        renderSummary(records, filteredRecords, 'Data imported from textarea.');
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
    try {
      const filters = readFilters(filterForm);
      filteredRecords = applyFilters(records, filters);
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, 'Filters applied.');
    } catch (error) {
      renderError('Failed to apply filters.', recordsContainer);
    }
  });

  // Add manual marker
  manualForm.addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      const manualRecord = readManualMarker(manualForm);
      const scoredRecord = scoreRecord(normalizeRecord(manualRecord));
      records.push(scoredRecord);
      records = sortRecords(records);
      filteredRecords = [...records];
      saveToLocalStorage(records);
      renderRecords(filteredRecords, recordsContainer);
      renderSummary(records, filteredRecords, 'Manual marker added.');
    } catch (error) {
      renderError('Failed to add manual marker.', recordsContainer);
    }
  });

  // Export filtered records
  exportButton.addEventListener('click', () => {
    try {
      exportData(filteredRecords, 'filtered_highlights.json');
      renderSummary(records, filteredRecords, 'Filtered records exported.');
    } catch (error) {
      renderError('Failed to export filtered records.', recordsContainer);
    }
  });
});