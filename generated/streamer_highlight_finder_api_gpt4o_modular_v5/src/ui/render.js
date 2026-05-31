// src/ui/render.js

/**
 * Renders a list of records into the specified container.
 * @param {Array} records - The list of records to render.
 * @param {HTMLElement} container - The container element to render the records into.
 */
export function renderRecords(records, container) {
  // Clear the container
  container.textContent = '';

  // Render each record
  records.forEach(record => {
    const recordElement = document.createElement('div');
    recordElement.className = 'record';

    // Safely append text content for each field
    const fields = [
      { label: 'Streamer', value: record.streamer },
      { label: 'Game', value: record.game },
      { label: 'Timestamp', value: record.timestamp },
      { label: 'Category', value: record.category },
      { label: 'Intensity', value: record.intensity },
      { label: 'Chat Rate', value: record.chatRate },
      { label: 'Keywords', value: record.keywords.join(', ') },
      { label: 'Title', value: record.title },
      { label: 'Description', value: record.description },
      { label: 'Score', value: record.score }
    ];

    fields.forEach(field => {
      const fieldElement = document.createElement('p');
      fieldElement.textContent = `${field.label}: ${field.value}`;
      recordElement.appendChild(fieldElement);
    });

    container.appendChild(recordElement);
  });
}

/**
 * Renders a summary of the records and filtered records into the summary element.
 * @param {Array} records - The full list of records.
 * @param {Array} filteredRecords - The filtered list of records.
 * @param {HTMLElement} summaryElement - The element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  // Clear the summary element
  summaryElement.textContent = '';

  // Create summary content
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  const summaryText = `Total Records: ${totalRecords}, Filtered Records: ${filteredCount}`;
  summaryElement.textContent = summaryText;
}

/**
 * Renders an error message into the specified container.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element to render the error message into.
 */
export function renderError(message, container) {
  // Clear the container
  container.textContent = '';

  // Create and append the error message
  const errorElement = document.createElement('div');
  errorElement.className = 'error';
  errorElement.textContent = `Error: ${message}`;
  container.appendChild(errorElement);
}