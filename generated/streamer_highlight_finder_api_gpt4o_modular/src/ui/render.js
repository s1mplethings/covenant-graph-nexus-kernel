// src/ui/render.js

/**
 * Renders a list of records into the specified container.
 * @param {Array} records - The list of records to render.
 * @param {HTMLElement} container - The container element where records will be rendered.
 */
export function renderRecords(records, container) {
  // Clear the container
  container.textContent = '';

  // Render each record
  records.forEach(record => {
    const recordElement = document.createElement('div');
    recordElement.className = 'record';

    // Safely append text content to avoid XSS
    const streamer = document.createElement('p');
    streamer.textContent = `Streamer: ${record.streamer}`;
    recordElement.appendChild(streamer);

    const game = document.createElement('p');
    game.textContent = `Game: ${record.game}`;
    recordElement.appendChild(game);

    const timestamp = document.createElement('p');
    timestamp.textContent = `Timestamp: ${record.timestamp}`;
    recordElement.appendChild(timestamp);

    const score = document.createElement('p');
    score.textContent = `Score: ${record.score}`;
    recordElement.appendChild(score);

    container.appendChild(recordElement);
  });
}

/**
 * Renders a summary of the records and filtered records into the summary element.
 * @param {Array} records - The full list of records.
 * @param {Array} filteredRecords - The filtered list of records.
 * @param {HTMLElement} summaryElement - The element where the summary will be rendered.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  // Clear the summary element
  summaryElement.textContent = '';

  // Create summary content
  const totalRecords = document.createElement('p');
  totalRecords.textContent = `Total Records: ${records.length}`;
  summaryElement.appendChild(totalRecords);

  const filteredCount = document.createElement('p');
  filteredCount.textContent = `Filtered Records: ${filteredRecords.length}`;
  summaryElement.appendChild(filteredCount);
}

/**
 * Renders an error message into the specified container.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element where the error will be rendered.
 */
export function renderError(message, container) {
  // Clear the container
  container.textContent = '';

  // Create and append the error message
  const errorElement = document.createElement('div');
  errorElement.className = 'error';
  errorElement.textContent = message;
  container.appendChild(errorElement);
}