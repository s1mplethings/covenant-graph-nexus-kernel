window.runSmokeTest = async function() {
  const recordsContainer = document.getElementById('records-container');
  const jsonTextarea = document.getElementById('json-textarea');
  const importButton = document.getElementById('import-button');
  const filterForm = document.getElementById('filter-form');
  const manualForm = document.getElementById('manual-form');
  const exportButton = document.getElementById('export-button');

  jsonTextarea.value = JSON.stringify([{ "streamer": "TestStreamer", "game": "TestGame", "category": "TestCategory", "timestamp": "00:00:01", "title": "TestTitle", "description": "TestDescription" }]);
  importButton.click();

  await new Promise(resolve => setTimeout(resolve, 1000)); // wait for import to process

  const scoreBadges = recordsContainer.querySelectorAll('.score-badge');
  scoreBadges.forEach(badge => {
    const score = parseInt(badge.textContent.match(/\d+/)[0], 10);
    if (isNaN(score) || score <= 0) {
      throw new Error('Score is not numeric or positive');
    }
  });

  const cards = recordsContainer.querySelectorAll('.highlight-card');
  const sortedScores = Array.from(scoreBadges).map(badge => parseInt(badge.textContent.match(/\d+/)[0], 10)).sort((a, b) => b - a);
  const actualScores = Array.from(scoreBadges).map(badge => parseInt(badge.textContent.match(/\d+/)[0], 10));
  if (JSON.stringify(actualScores) !== JSON.stringify(sortedScores)) {
    throw new Error('Records are not sorted in descending order by score');
  }

  const filterStreamer = document.getElementById('filterStreamer');
  const filterGame = document.getElementById('filterGame');
  const filterCategory = document.getElementById('filterCategory');
  const filterScore = document.getElementById('filterScore');

  filterStreamer.value = 'TestStreamer';
  filterGame.value = 'TestGame';
  filterCategory.value = 'TestCategory';
  filterScore.value = '1';
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  await new Promise(resolve => setTimeout(resolve, 1000)); // wait for filter to process

  filterStreamer.value = '';
  filterGame.value = '';
  filterCategory.value = '';
  filterScore.value = '';
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  const manualTitleInput = manualForm.querySelector('[name="title"]');
  const manualStreamerInput = manualForm.querySelector('[name="streamer"]');
  manualTitleInput.value = 'ManualTestTitle';
  manualStreamerInput.value = 'ManualTestStreamer';
  manualForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  await new Promise(resolve => setTimeout(resolve, 1000)); // wait for manual marker to process

  const manualScoreBadge = recordsContainer.querySelector('.score-badge');
  const manualScore = parseInt(manualScoreBadge.textContent.match(/\d+/)[0], 10);
  if (isNaN(manualScore) || manualScore <= 0) {
    throw new Error('Manual marker score is not numeric or positive');
  }

  const localStorageRecords = JSON.parse(localStorage.getItem('cgnk.streamerHighlightFinder.records'));
  if (!localStorageRecords.some(record => record.title === 'ManualTestTitle' && record.streamer === 'ManualTestStreamer')) {
    throw new Error('Manual record not found in localStorage');
  }

  const visibleCards = Array.from(recordsContainer.querySelectorAll('.highlight-card'));
  if (!visibleCards.some(card => card.querySelector('.highlight-title').textContent === 'ManualTestTitle' && card.querySelector('.metadata-streamer').textContent.includes('ManualTestStreamer'))) {
    throw new Error('Manual record not visible in results');
  }

  const downloadPathTriggered = new Promise(resolve => {
    const originalCreateObjectURL = URL.createObjectURL;
    URL.createObjectURL = function() {
      resolve(true);
      return originalCreateObjectURL.apply(this, arguments);
    };
  });
  exportButton.click();

  await downloadPathTriggered;

  return { status: 'pass' };
};
