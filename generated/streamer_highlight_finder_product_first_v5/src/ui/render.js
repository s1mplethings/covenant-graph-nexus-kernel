// src/ui/render.js

/**
 * Renders highlight records into the specified container.
 * @param {Array} records - Array of highlight records.
 * @param {HTMLElement} container - The container element to render the records into.
 */
export function renderRecords(records, container) {
  // Clear the container
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }

  // Create and append highlight cards
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

    // Metadata: Time
    const timeMeta = document.createElement('p');
    timeMeta.classList.add('metadata-row', 'metadata-time');
    timeMeta.textContent = `Time: ${record.time || 'Unknown'}`;
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

    // Append card to container
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
  // Clear the container
  while (container.firstChild) {
    container.removeChild(container.firstChild);
  }

  // Create and append error message
  const errorMessage = document.createElement('p');
  errorMessage.classList.add('error-message');
  errorMessage.textContent = message;
  container.appendChild(errorMessage);
}