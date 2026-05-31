// src/ui/render.js

/**
 * Escapes HTML special characters in a string to prevent XSS.
 * @param {string} str - The string to escape.
 * @returns {string} - The escaped string.
 */
function escapeHTML(str) {
  return str.replace(/[&<>"']/g, (char) => {
    const escapeMap = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;',
    };
    return escapeMap[char];
  });
}

/**
 * Renders a list of records into a container element.
 * @param {Array<Object>} records - The records to render.
 * @param {HTMLElement} container - The container element to render into.
 */
export function renderRecords(records, container) {
  container.innerHTML = ''; // Clear previous content
  const table = document.createElement('table');
  table.className = 'records-table';

  // Create table header
  const headerRow = document.createElement('tr');
  ['Streamer', 'Game', 'Timestamp', 'Category', 'Score', 'Title', 'Description'].forEach((header) => {
    const th = document.createElement('th');
    th.textContent = header;
    headerRow.appendChild(th);
  });
  table.appendChild(headerRow);

  // Create table rows for each record
  records.forEach((record) => {
    const row = document.createElement('tr');
    [
      escapeHTML(record.streamer),
      escapeHTML(record.game),
      escapeHTML(record.timestamp),
      escapeHTML(record.category),
      record.score.toFixed(2),
      escapeHTML(record.title),
      escapeHTML(record.description),
    ].forEach((cellData) => {
      const td = document.createElement('td');
      td.textContent = cellData;
      row.appendChild(td);
    });
    table.appendChild(row);
  });

  container.appendChild(table);
}

/**
 * Renders a summary of records into a summary element.
 * @param {Array<Object>} records - The full dataset of records.
 * @param {Array<Object>} filteredRecords - The filtered dataset of records.
 * @param {HTMLElement} summaryElement - The summary element to render into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  summaryElement.textContent = `Showing ${filteredCount} of ${totalRecords} records.`;
}

/**
 * Renders an error message into a container element.
 * @param {string} message - The error message to render.
 * @param {HTMLElement} container - The container element to render into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear previous content
  const errorDiv = document.createElement('div');
  errorDiv.className = 'error-message';
  errorDiv.textContent = escapeHTML(message);
  container.appendChild(errorDiv);
}