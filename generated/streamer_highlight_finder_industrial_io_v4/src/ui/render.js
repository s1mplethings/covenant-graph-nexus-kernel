// src/ui/render.js

/**
 * Renders highlight records into the specified container.
 * @param {Array} records - Array of highlight records.
 * @param {HTMLElement} container - The container element to render the records into.
 */
export function renderRecords(records, container) {
  container.innerHTML = ''; // Clear previous content

  records.forEach(record => {
    const card = document.createElement('div');
    card.classList.add('highlight-card');

    // Title
    const title = document.createElement('h3');
    title.classList.add('highlight-title');
    title.textContent = record.title || 'Untitled Highlight';
    card.appendChild(title);

    // Score Badge
    const scoreBadge = document.createElement('span');
    scoreBadge.classList.add('score-badge');
    scoreBadge.textContent = `Score: ${record.score.toFixed(2)}`;
    card.appendChild(scoreBadge);

    // Metadata Rows
    const streamerRow = document.createElement('p');
    streamerRow.classList.add('metadata-row', 'metadata-streamer');
    streamerRow.textContent = `Streamer: ${record.streamer || 'Unknown'}`;
    card.appendChild(streamerRow);

    const gameRow = document.createElement('p');
    gameRow.classList.add('metadata-row', 'metadata-game');
    gameRow.textContent = `Game: ${record.game || 'Unknown'}`;
    card.appendChild(gameRow);

    const timeRow = document.createElement('p');
    timeRow.classList.add('metadata-row', 'metadata-time');
    timeRow.textContent = `Time: ${record.time || 'Unknown'} seconds`;
    card.appendChild(timeRow);

    const categoryRow = document.createElement('p');
    categoryRow.classList.add('metadata-row', 'metadata-category');
    categoryRow.textContent = `Category: ${record.category || 'Uncategorized'}`;
    card.appendChild(categoryRow);

    // Description
    const description = document.createElement('p');
    description.classList.add('highlight-description');
    description.textContent = record.description || 'No description available.';
    card.appendChild(description);

    // Keywords (if present)
    if (record.keywords && record.keywords.length > 0) {
      const keywordsRow = document.createElement('p');
      keywordsRow.classList.add('metadata-row', 'metadata-keywords');
      keywordsRow.textContent = `Keywords: ${record.keywords.join(', ')}`;
      card.appendChild(keywordsRow);
    }

    container.appendChild(card);
  });
}

/**
 * Renders a summary of the records and filtered results into the specified summary element.
 * @param {Array} records - Array of all records.
 * @param {Array} filteredRecords - Array of filtered records.
 * @param {HTMLElement} summaryElement - The summary element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  summaryElement.textContent = `Showing ${filteredCount} of ${totalRecords} records.`;
}

/**
 * Renders an error message into the specified container.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element to render the error into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear previous content

  const errorElement = document.createElement('div');
  errorElement.classList.add('error-message');
  errorElement.textContent = `Error: ${message}`;
  container.appendChild(errorElement);
}