// src/ui/render.js

/**
 * Renders highlight records into the specified container.
 * @param {Array} records - Array of highlight records.
 * @param {HTMLElement} container - DOM element to render the records into.
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
    scoreBadge.textContent = `Score: ${record.score}`;
    card.appendChild(scoreBadge);

    // Metadata: Streamer
    const streamerMeta = document.createElement('p');
    streamerMeta.classList.add('metadata-row', 'metadata-streamer');
    streamerMeta.textContent = `Streamer: ${record.streamer || 'Unknown'}`;
    card.appendChild(streamerMeta);

    // Metadata: Game
    const gameMeta = document.createElement('p');
    gameMeta.classList.add('metadata-row', 'metadata-game');
    gameMeta.textContent = `Game: ${record.game || 'Unknown'}`;
    card.appendChild(gameMeta);

    // Metadata: Timestamp/Time
    const timeMeta = document.createElement('p');
    timeMeta.classList.add('metadata-row', 'metadata-time');
    timeMeta.textContent = `Time: ${record.timestamp || record.time || 'Unknown'}`;
    card.appendChild(timeMeta);

    // Metadata: Category
    const categoryMeta = document.createElement('p');
    categoryMeta.classList.add('metadata-row', 'metadata-category');
    categoryMeta.textContent = `Category: ${record.category || 'Uncategorized'}`;
    card.appendChild(categoryMeta);

    // Description
    const description = document.createElement('p');
    description.classList.add('highlight-description');
    description.textContent = record.description || 'No description available.';
    card.appendChild(description);

    // Keywords (if present)
    if (record.keywords && record.keywords.length > 0) {
      const keywordsMeta = document.createElement('p');
      keywordsMeta.classList.add('metadata-row', 'metadata-keywords');
      keywordsMeta.textContent = `Keywords: ${record.keywords.join(', ')}`;
      card.appendChild(keywordsMeta);
    }

    container.appendChild(card);
  });
}

/**
 * Renders a summary of the records and filtered records into the summary element.
 * @param {Array} records - Array of all records.
 * @param {Array} filteredRecords - Array of filtered records.
 * @param {HTMLElement} summaryElement - DOM element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  summaryElement.textContent = `Showing ${filteredCount} of ${totalRecords} records.`;
}

/**
 * Renders an error message into the specified container.
 * @param {string} message - Error message to display.
 * @param {HTMLElement} container - DOM element to render the error message into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear previous content

  const errorElement = document.createElement('div');
  errorElement.classList.add('error-message');
  errorElement.textContent = `Error: ${message}`;
  container.appendChild(errorElement);
}