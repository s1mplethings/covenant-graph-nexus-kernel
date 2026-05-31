const highlights = [];

function scoreRecord(record) {
    // Example scoring logic based on intensity and chat rate
    return (record.intensity * 10) + (record.chatRate * 2);
}

function processImportedData(data) {
    data.forEach(record => {
        record.score = scoreRecord(record);
        highlights.push(record);
    });
    sortHighlights();
    renderHighlights();
}

function sortHighlights() {
    highlights.sort((a, b) => b.score - a.score);
}

function renderHighlights() {
    const resultsDiv = document.getElementById('results');
    resultsDiv.innerHTML = '';
    highlights.forEach(highlight => {
        const div = document.createElement('div');
        div.className = 'highlight';
        div.innerHTML = `<strong>${highlight.title}</strong><br>${highlight.description}<br>Score: ${highlight.score}`;
        resultsDiv.appendChild(div);
    });
}

document.getElementById('fileInput').addEventListener('change', (event) => {
    const file = event.target.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
        const data = JSON.parse(e.target.result);
        processImportedData(data);
    };
    reader.readAsText(file);
});

document.getElementById('filterButton').addEventListener('click', () => {
    const streamer = document.getElementById('filterStreamer').value;
    const game = document.getElementById('filterGame').value;
    const minScore = parseInt(document.getElementById('filterScore').value);
    const filtered = highlights.filter(h =>
        (!streamer || h.streamer.includes(streamer)) &&
        (!game || h.game.includes(game)) &&
        (!minScore || h.score >= minScore)
    );
    renderFilteredHighlights(filtered);
});

function renderFilteredHighlights(filtered) {
    const resultsDiv = document.getElementById('results');
    resultsDiv.innerHTML = '';
    filtered.forEach(highlight => {
        const div = document.createElement('div');
        div.className = 'highlight';
        div.innerHTML = `<strong>${highlight.title}</strong><br>${highlight.description}<br>Score: ${highlight.score}`;
        resultsDiv.appendChild(div);
    });
}

document.getElementById('addMarkerButton').addEventListener('click', () => {
    const title = document.getElementById('markerTitle').value;
    const description = document.getElementById('markerDescription').value;
    const newRecord = { title, description, score: 0 }; // Score will be calculated later
    highlights.push(newRecord);
    renderHighlights();
});

document.getElementById('exportButton').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(highlights)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'highlights.json';
    a.click();
    URL.revokeObjectURL(url);
});

window.onload = () => {
    const storedData = localStorage.getItem('highlights');
    if (storedData) {
        highlights.push(...JSON.parse(storedData));
        renderHighlights();
    }
};

window.onbeforeunload = () => {
    localStorage.setItem('highlights', JSON.stringify(highlights));
};