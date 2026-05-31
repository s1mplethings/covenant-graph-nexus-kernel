// src/ui/render.js

/**
 * Renders highlight records into the specified container.
 * @param {Array} records - Array of highlight records.
 * @param {HTMLElement} container - The container element to render the records into.
 */
export function renderRecords(records, container) {
  container.innerHTML = ''; // Clear existing content

  records.forEach(record => {
    const card = document.createElement('div');
    card.className = 'highlight-card';

    // Title
    const title = document.createElement('h3');
    title.className = 'highlight-title';
    title.textContent = record.title || 'Untitled Highlight';
    card.appendChild(title);

    // Score Badge
    const scoreBadge = document.createElement('span');
    scoreBadge.className = 'score-badge';
    scoreBadge.textContent = `Score: ${record.score}`;
    card.appendChild(scoreBadge);

    // Metadata Rows
    const metadata = document.createElement('div');
    metadata.className = 'metadata-row';

    const streamer = document.createElement('p');
    streamer.textContent = `Streamer: ${record.streamer}`;
    metadata.appendChild(streamer);

    const game = document.createElement('p');
    game.textContent = `Game: ${record.game}`;
    metadata.appendChild(game);

    const timestamp = document.createElement('p');
    timestamp.textContent = `Timestamp: ${record.timestamp}`;
    metadata.appendChild(timestamp);

    const category = document.createElement('p');
    category.textContent = `Category: ${record.category}`;
    metadata.appendChild(category);

    card.appendChild(metadata);

    // Description
    const description = document.createElement('p');
    description.textContent = record.description || 'No description available.';
    card.appendChild(description);

    // Keywords (if present)
    if (record.keywords && record.keywords.length > 0) {
      const keywords = document.createElement('p');
      keywords.textContent = `Keywords: ${record.keywords.join(', ')}`;
      card.appendChild(keywords);
    }

    container.appendChild(card);
  });
}

/**
 * Renders a summary of the records and filtered records into the summary element.
 * @param {Array} records - Array of all records.
 * @param {Array} filteredRecords - Array of filtered records.
 * @param {HTMLElement} summaryElement - The element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  summaryElement.textContent = `Showing ${filteredCount} of ${totalRecords} highlights.`;
}

/**
 * Renders an error message into the specified container.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element to render the error into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear existing content

  const errorElement = document.createElement('div');
  errorElement.className = 'error-message';
  errorElement.textContent = `Error: ${message}`;
  container.appendChild(errorElement);
}