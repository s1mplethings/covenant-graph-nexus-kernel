const records = JSON.parse(localStorage.getItem('records')) || [];
let filters = {
  streamer: '',
  game: '',
  category: '',
  minScore: 0
};

function scoreRecord(record) {
  const intensityWeight = record.intensity || 0;
  const chatRateWeight = record.chatRate || 0;
  const keywordWeight = (record.keywords || []).length * 2;
  return intensityWeight + chatRateWeight + keywordWeight;
}

function applyFilters() {
  return records.filter(record => {
    return (
      String(record.streamer || '').toLowerCase().includes(filters.streamer.toLowerCase()) &&
      String(record.game || '').toLowerCase().includes(filters.game.toLowerCase()) &&
      String(record.category || '').toLowerCase().includes(filters.category.toLowerCase()) &&
      (record.score || 0) >= filters.minScore
    );
  });
}

function renderRecords() {
  const filteredRecords = applyFilters();
  const container = document.getElementById('records-container');
  container.innerHTML = '';
  filteredRecords.forEach(record => {
    const div = document.createElement('div');
    div.textContent = `${record.streamer} - ${record.game} - ${record.category} - Score: ${record.score}`;
    container.appendChild(div);
  });
}

function handleFileImport(event) {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = function(e) {
      const importedRecords = JSON.parse(e.target.result);
      importedRecords.forEach(record => {
        record.score = scoreRecord(record);
      });
      records.push(...importedRecords);
      records.sort((a, b) => b.score - a.score);
      localStorage.setItem('records', JSON.stringify(records));
      renderRecords();
    };
    reader.readAsText(file);
  }
}

function handleFilterChange(event) {
  const { name, value } = event.target;
  filters[name] = name === 'minScore' ? Number(value) : value;
  renderRecords();
}

function handleManualFormSubmit(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const newRecord = {
    streamer: formData.get('streamer'),
    game: formData.get('game'),
    category: formData.get('category'),
    intensity: Number(formData.get('intensity')),
    chatRate: Number(formData.get('chatRate')),
    keywords: formData.get('keywords').split(',').map(k => k.trim()),
    title: formData.get('title'),
    description: formData.get('description'),
    timestamp: formData.get('timestamp'),
    score: 0
  };
  newRecord.score = scoreRecord(newRecord);
  records.push(newRecord);
  records.sort((a, b) => b.score - a.score);
  localStorage.setItem('records', JSON.stringify(records));
  renderRecords();
  event.target.reset();
}

function handleExport() {
  const filteredRecords = applyFilters();
  const blob = new Blob([JSON.stringify(filteredRecords, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'filtered_records.json';
  a.click();
  URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('file-input').addEventListener('change', handleFileImport);
  document.getElementById('filter-form').addEventListener('input', handleFilterChange);
  document.getElementById('manual-form').addEventListener('submit', handleManualFormSubmit);
  document.getElementById('export-button').addEventListener('click', handleExport);
  renderRecords();
});