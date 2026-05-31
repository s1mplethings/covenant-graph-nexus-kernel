// src/ui/render.js

/**
 * Escapes HTML special characters in user-provided data to prevent XSS.
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
 * Renders highlight records into the provided container element.
 * @param {Array} records - Array of highlight records.
 * @param {HTMLElement} container - The container element to render the records into.
 */
export function renderRecords(records, container) {
  container.innerHTML = ''; // Clear previous content

  records.forEach((record) => {
    const card = document.createElement('div');
    card.className = 'highlight-card';

    const title = document.createElement('h3');
    title.className = 'highlight-title';
    title.textContent = escapeHTML(record.title);

    const scoreBadge = document.createElement('span');
    scoreBadge.className = 'score-badge';
    scoreBadge.textContent = `Score: ${record.score}`;

    const streamerRow = document.createElement('p');
    streamerRow.className = 'metadata-row metadata-streamer';
    streamerRow.textContent = `Streamer: ${escapeHTML(record.streamer)}`;

    const gameRow = document.createElement('p');
    gameRow.className = 'metadata-row metadata-game';
    gameRow.textContent = `Game: ${escapeHTML(record.game)}`;

    const timeRow = document.createElement('p');
    timeRow.className = 'metadata-row metadata-time';
    timeRow.textContent = `Time: ${escapeHTML(record.timestamp)}`;

    const categoryRow = document.createElement('p');
    categoryRow.className = 'metadata-row metadata-category';
    categoryRow.textContent = `Category: ${escapeHTML(record.category)}`;

    const description = document.createElement('p');
    description.className = 'highlight-description';
    description.textContent = escapeHTML(record.description);

    card.appendChild(title);
    card.appendChild(scoreBadge);
    card.appendChild(streamerRow);
    card.appendChild(gameRow);
    card.appendChild(timeRow);
    card.appendChild(categoryRow);
    card.appendChild(description);

    if (record.keywords && record.keywords.length > 0) {
      const keywordsRow = document.createElement('p');
      keywordsRow.className = 'metadata-row metadata-keywords';
      keywordsRow.textContent = `Keywords: ${record.keywords.map(escapeHTML).join(', ')}`;
      card.appendChild(keywordsRow);
    }

    container.appendChild(card);
  });
}

/**
 * Renders a summary of the records and filtered results into the provided summary element.
 * @param {Array} records - Array of all records.
 * @param {Array} filteredRecords - Array of filtered records.
 * @param {HTMLElement} summaryElement - The element to render the summary into.
 */
export function renderSummary(records, filteredRecords, summaryElement) {
  const totalRecords = records.length;
  const filteredCount = filteredRecords.length;

  summaryElement.textContent = `Total Records: ${totalRecords}, Filtered Records: ${filteredCount}`;
}

/**
 * Renders an error message into the provided container element.
 * @param {string} message - The error message to display.
 * @param {HTMLElement} container - The container element to render the error into.
 */
export function renderError(message, container) {
  container.innerHTML = ''; // Clear previous content

  const errorElement = document.createElement('div');
  errorElement.className = 'error-message';
  errorElement.textContent = escapeHTML(message);

  container.appendChild(errorElement);
}