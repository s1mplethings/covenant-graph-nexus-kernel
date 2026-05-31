// src/ui/render.js

/**
 * Escapes HTML special characters to prevent XSS attacks.
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
      "'": '&#39;',
    };
    return escapeMap[char];
  });
}

/**
 * Renders a list of records into a container element.
 * @param {Array} records - The list of records to render.
 * @param {HTMLElement} container - The container element to render into.
 */
export function renderRecords(records, container) {
  container.innerHTML = ''; // Clear existing content
  records.forEach((record) => {
    const recordElement = document.createElement('div');
    recordElement.className = 'record-item';

    // Safely render record fields
    recordElement.innerHTML = `
      <div><strong>Streamer:</strong> ${escapeHTML(record.streamer)}</div>
      <div><strong>Game:</strong> ${escapeHTML(record.game)}</div>
      <div><strong>Timestamp:</strong> ${escapeHTML(record.timestamp)}</div>
      <div><strong>Category:</strong> ${escapeHTML(record.category)}</div>
      <div><strong>Score:</strong> ${record.score}</div>
      <div><strong>Description:</strong> ${escapeHTML(record.description)}</div>
    `;

    container.appendChild(recordElement);
  });
}

/**
 * Renders a summary of the records and filtered records into a summary element.
 * @param {Array} records - The full list of records.
 * @param {Array} filteredRecords - The filtered list of records.
 * @param {HTMLElement} summaryElement - The element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  // Safely set the summary text
  summaryElement.textContent = `Showing ${filteredCount} of ${totalRecords} records.`;
}

/**
 * Renders an error message into a container element.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element to render the error into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear existing content

  const errorElement = document.createElement('div');
  errorElement.className = 'error-message';

  // Safely set the error message
  errorElement.textContent = `Error: ${message}`;

  container.appendChild(errorElement);
}