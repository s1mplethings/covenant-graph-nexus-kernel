export function renderRecords(records, container) {
    // Clear the container before rendering
    container.innerHTML = '';

    records.forEach(record => {
        const card = document.createElement('div');
        card.classList.add('highlight-card');

        const title = document.createElement('h3');
        title.classList.add('highlight-title');
        title.textContent = escapeHtml(record.title);
        card.appendChild(title);

        const scoreBadge = document.createElement('span');
        scoreBadge.classList.add('score-badge');
        scoreBadge.textContent = `Score: ${record.score}`;
        card.appendChild(scoreBadge);

        const metadataStreamer = document.createElement('p');
        metadataStreamer.classList.add('metadata-row', 'metadata-streamer');
        metadataStreamer.textContent = `Streamer: ${escapeHtml(record.streamer)}`;
        card.appendChild(metadataStreamer);

        const metadataGame = document.createElement('p');
        metadataGame.classList.add('metadata-row', 'metadata-game');
        metadataGame.textContent = `Game: ${escapeHtml(record.game)}`;
        card.appendChild(metadataGame);

        const metadataTime = document.createElement('p');
        metadataTime.classList.add('metadata-row', 'metadata-time');
        metadataTime.textContent = `Time: ${escapeHtml(record.time || record.timestamp)}`;
        card.appendChild(metadataTime);

        const metadataCategory = document.createElement('p');
        metadataCategory.classList.add('metadata-row', 'metadata-category');
        metadataCategory.textContent = `Category: ${escapeHtml(record.category)}`;
        card.appendChild(metadataCategory);

        const description = document.createElement('p');
        description.classList.add('highlight-description');
        description.textContent = escapeHtml(record.description);
        card.appendChild(description);

        // Append the card to the container
        container.appendChild(card);
    });
}

export function renderSummary(records, filteredRecords, summaryElement) {
    const totalRecords = records.length;
    const filteredCount = filteredRecords.length;

    summaryElement.textContent = `Total Records: ${totalRecords}, Filtered Records: ${filteredCount}`;
}

export function renderError(message, container) {
    container.innerHTML = ''; // Clear previous content
    const errorElement = document.createElement('div');
    errorElement.classList.add('error-message');
    errorElement.textContent = escapeHtml(message);
    container.appendChild(errorElement);
}

function escapeHtml(unsafe) {
    return String(unsafe ?? '')
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
