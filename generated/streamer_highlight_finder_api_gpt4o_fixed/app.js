const fileInput = document.getElementById('file-input');
const jsonTextarea = document.getElementById('json-textarea');
const importButton = document.getElementById('import-button');
const filterForm = document.getElementById('filter-form');
const filterStreamer = document.getElementById('filterStreamer');
const filterGame = document.getElementById('filterGame');
const filterCategory = document.getElementById('filterCategory');
const filterScore = document.getElementById('filterScore');
const manualForm = document.getElementById('manual-form');
const exportButton = document.getElementById('export-button');
const recordsContainer = document.getElementById('records-container');

let records = [];
let filteredRecords = [];

function scoreRecord(record) {
  const intensity = record.intensity || 0;
  const chatRate = record.chatRate || 0;
  const keywords = (record.keywords || []).length;
  return intensity * 2 + chatRate + keywords * 3;
}

function renderRecords() {
  recordsContainer.innerHTML = '';
  filteredRecords.forEach(record => {
    const recordDiv = document.createElement('div');
    recordDiv.textContent = JSON.stringify(record);
    recordsContainer.appendChild(recordDiv);
  });
}

function applyFilters() {
  const streamerFilter = filterStreamer.value.toLowerCase();
  const gameFilter = filterGame.value.toLowerCase();
  const categoryFilter = filterCategory.value.toLowerCase();
  const scoreFilter = parseFloat(filterScore.value) || 0;

  filteredRecords = records.filter(record => {
    return (
      String(record.streamer || '').toLowerCase().includes(streamerFilter) &&
      String(record.game || '').toLowerCase().includes(gameFilter) &&
      String(record.category || '').toLowerCase().includes(categoryFilter) &&
      (record.score || 0) >= scoreFilter
    );
  });

  renderRecords();
}

function saveToLocalStorage() {
  localStorage.setItem('highlightRecords', JSON.stringify(records));
}

function loadFromLocalStorage() {
  const savedRecords = localStorage.getItem('highlightRecords');
  if (savedRecords) {
    records = JSON.parse(savedRecords);
    records.forEach(record => {
      record.score = scoreRecord(record);
    });
    applyFilters();
  }
}

function handleFileImport(event) {
  const file = fileInput.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const importedData = JSON.parse(e.target.result);
      importedData.forEach(item => {
        item.score = scoreRecord(item);
        records.push(item);
      });
      records.sort((a, b) => b.score - a.score);
      applyFilters();
      saveToLocalStorage();
    } catch (error) {
      alert('Invalid JSON file');
    }
  };
  reader.readAsText(file);
}

function handleTextareaImport() {
  try {
    const importedData = JSON.parse(jsonTextarea.value);
    importedData.forEach(item => {
      item.score = scoreRecord(item);
      records.push(item);
    });
    records.sort((a, b) => b.score - a.score);
    applyFilters();
    saveToLocalStorage();
  } catch (error) {
    alert('Invalid JSON data');
  }
}

function handleManualFormSubmit(event) {
  event.preventDefault();
  const formData = new FormData(manualForm);
  const newRecord = {
    streamer: formData.get('streamer'),
    game: formData.get('game'),
    timestamp: formData.get('timestamp'),
    category: formData.get('category'),
    intensity: parseFloat(formData.get('intensity')) || 0,
    chatRate: parseFloat(formData.get('chatRate')) || 0,
    keywords: formData.get('keywords') ? formData.get('keywords').split(',') : [],
    title: formData.get('title'),
    description: formData.get('description'),
  };
  newRecord.score = scoreRecord(newRecord);
  records.push(newRecord);
  records.sort((a, b) => b.score - a.score);
  applyFilters();
  saveToLocalStorage();
  manualForm.reset();
}

function handleExport() {
  const blob = new Blob([JSON.stringify(filteredRecords, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'filtered_records.json';
  a.click();
  URL.revokeObjectURL(url);
}

importButton.addEventListener('click', handleTextareaImport);
fileInput.addEventListener('change', handleFileImport);
filterForm.addEventListener('input', applyFilters);
manualForm.addEventListener('submit', handleManualFormSubmit);
exportButton.addEventListener('click', handleExport);

loadFromLocalStorage();