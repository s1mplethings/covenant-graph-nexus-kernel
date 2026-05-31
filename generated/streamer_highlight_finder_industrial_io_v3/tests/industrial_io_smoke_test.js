window.runIndustrialIOSmokeTest = async function() {
  const inputBundleUrl = 'data/industrial_input_bundle.json';
  const expectedOutputsUrl = 'data/expected_outputs.json';

  // Fetch industrial input bundle and expected outputs
  const [inputBundleResponse, expectedOutputsResponse] = await Promise.all([
    fetch(inputBundleUrl),
    fetch(expectedOutputsUrl)
  ]);

  if (!inputBundleResponse.ok || !expectedOutputsResponse.ok) {
    throw new Error('Failed to fetch input bundle or expected outputs.');
  }

  const inputBundle = await inputBundleResponse.json();
  const expectedOutputs = await expectedOutputsResponse.json();

  // Locate DOM elements
  const jsonTextarea = document.getElementById('json-textarea');
  const importButton = document.getElementById('import-button');
  const recordsContainer = document.getElementById('records-container');
  const filterForm = document.getElementById('filter-form');
  const exportButton = document.getElementById('export-button');

  if (!jsonTextarea || !importButton || !recordsContainer || !filterForm || !exportButton) {
    throw new Error('Required DOM elements are missing.');
  }

  // Step 1: Paste industrial input bundle into the textarea
  jsonTextarea.value = JSON.stringify(inputBundle);

  // Step 2: Click the import button
  importButton.dispatchEvent(new Event('click', { bubbles: true, cancelable: true }));

  // Step 3: Verify localStorage records
  const storedRecords = JSON.parse(localStorage.getItem('cgnk.streamerHighlightFinder.records'));
  if (!storedRecords || storedRecords.length < 20) {
    throw new Error('Less than 20 records were imported into localStorage.');
  }

  // Step 4: Verify visible output cards
  const visibleCards = Array.from(recordsContainer.getElementsByClassName('highlight-card'));
  if (visibleCards.length === 0) {
    throw new Error('No visible output cards found.');
  }

  // Verify scores are numeric and descending
  const scores = visibleCards.map(card => {
    const scoreBadge = card.querySelector('.score-badge');
    if (!scoreBadge) throw new Error('Score badge missing on a card.');
    const scoreMatch = scoreBadge.textContent.match(/\d+(\.\d+)?/);
    if (!scoreMatch) throw new Error('Score is not numeric.');
    return parseFloat(scoreMatch[0]);
  });

  if (!scores.every((score, i) => i === 0 || score <= scores[i - 1])) {
    throw new Error('Scores are not in descending order.');
  }

  // Verify at least one expected top-ranked title or streamer appears
  const visibleTitles = visibleCards.map(card => card.querySelector('.highlight-title')?.textContent || '');
  const visibleStreamers = visibleCards.map(card => card.querySelector('.metadata-streamer')?.textContent || '');
  const expectedTitlesOrStreamers = expectedOutputs.topRankedTitlesOrStreamers;

  if (!expectedTitlesOrStreamers.some(expected => visibleTitles.includes(expected) || visibleStreamers.includes(expected))) {
    throw new Error('No expected top-ranked title or streamer appears.');
  }

  // Verify source coverage includes at least 3 sourceIds in storage
  const sourceIds = new Set(storedRecords.map(record => record.sourceId));
  if (sourceIds.size < 3) {
    throw new Error('Source coverage includes less than 3 sourceIds.');
  }

  // Step 5: Test filtering by streamer or game
  const filterStreamerInput = filterForm.querySelector('#filterStreamer');
  const filterGameInput = filterForm.querySelector('#filterGame');

  if (!filterStreamerInput || !filterGameInput) {
    throw new Error('Filter inputs for streamer or game are missing.');
  }

  filterStreamerInput.value = storedRecords[0].streamer;
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  const filteredCardsByStreamer = Array.from(recordsContainer.getElementsByClassName('highlight-card'));
  if (!filteredCardsByStreamer.every(card => card.querySelector('.metadata-streamer')?.textContent === storedRecords[0].streamer)) {
    throw new Error('Filtering by streamer failed.');
  }

  filterStreamerInput.value = '';
  filterGameInput.value = storedRecords[0].game;
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  const filteredCardsByGame = Array.from(recordsContainer.getElementsByClassName('highlight-card'));
  if (!filteredCardsByGame.every(card => card.querySelector('.metadata-game')?.textContent === storedRecords[0].game)) {
    throw new Error('Filtering by game failed.');
  }

  // Step 6: Test export functionality
  exportButton.dispatchEvent(new Event('click', { bubbles: true, cancelable: true }));

  const exportAnchor = document.querySelector('a[download]');
  if (!exportAnchor || !exportAnchor.href.startsWith('blob:')) {
    throw new Error('Export functionality failed.');
  }

  return {
    status: 'pass',
    importedCount: storedRecords.length,
    visibleCount: visibleCards.length,
    checkedOutputs: {
      scoresDescending: true,
      topRankedTitleOrStreamerAppears: true,
      sourceCoverage: sourceIds.size,
      filteringWorks: true,
      exportWorks: true
    }
  };
};