window.runSmokeTest = async function() {
  const recordsContainer = document.getElementById('records-container');
  if (!recordsContainer) throw new Error("Missing records container");

  const jsonTextarea = document.getElementById('json-textarea');
  const importButton = document.getElementById('import-button');
  const filterForm = document.getElementById('filter-form');
  const manualForm = document.getElementById('manual-form');
  const exportButton = document.getElementById('export-button');

  if (!jsonTextarea || !importButton || !filterForm || !manualForm || !exportButton) {
    throw new Error("Missing one or more required DOM elements");
  }

  // Step 1: Import sample data
  const sampleData = JSON.stringify([
    {
      streamer: "Streamer1",
      game: "Game1",
      timestamp: "2023-01-01T12:00:00Z",
      time: 3600,
      category: "Category1",
      intensity: 80,
      chatRate: 50,
      keywords: ["highlight", "amazing"],
      title: "Epic Moment",
      description: "An amazing highlight",
    },
    {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-01-02T14:00:00Z",
      time: 7200,
      category: "Category2",
      intensity: 90,
      chatRate: 70,
      keywords: ["awesome", "clutch"],
      title: "Clutch Play",
      description: "A clutch play highlight",
    }
  ]);

  jsonTextarea.value = sampleData;
  importButton.click();

  // Wait for records to render
  await new Promise(resolve => setTimeout(resolve, 500));

  // Step 2: Verify imported records
  const cards = recordsContainer.querySelectorAll('.highlight-card');
  if (cards.length !== 2) throw new Error("Expected 2 records to be rendered");

  cards.forEach(card => {
    const title = card.querySelector('.highlight-title');
    const streamer = card.querySelector('.metadata-streamer');
    const game = card.querySelector('.metadata-game');
    const category = card.querySelector('.metadata-category');
    const description = card.querySelector('.highlight-description');
    const scoreBadge = card.querySelector('.score-badge');

    if (!title || !streamer || !game || !category || !description || !scoreBadge) {
      throw new Error("Missing required fields in rendered card");
    }

    const score = parseFloat(scoreBadge.textContent.match(/\d+(\.\d+)?/)[0]);
    if (isNaN(score) || score <= 0) {
      throw new Error("Invalid or non-positive score in rendered card");
    }
  });

  // Step 3: Verify sorting by score descending
  const scores = Array.from(cards).map(card => parseFloat(card.querySelector('.score-badge').textContent.match(/\d+(\.\d+)?/)[0]));
  if (!scores.every((score, i) => i === 0 || score <= scores[i - 1])) {
    throw new Error("Records are not sorted by score descending");
  }

  // Step 4: Test filtering
  const filterStreamer = document.getElementById('filterStreamer');
  filterStreamer.value = "Streamer1";
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  await new Promise(resolve => setTimeout(resolve, 500));

  const filteredCards = recordsContainer.querySelectorAll('.highlight-card');
  if (filteredCards.length !== 1 || !filteredCards[0].querySelector('.metadata-streamer').textContent.includes("Streamer1")) {
    throw new Error("Filtering by streamer failed");
  }

  // Clear filters
  filterStreamer.value = "";
  document.getElementById('filterGame').value = "";
  document.getElementById('filterCategory').value = "";
  document.getElementById('filterScore').value = "";
  filterForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  await new Promise(resolve => setTimeout(resolve, 500));

  if (recordsContainer.querySelectorAll('.highlight-card').length !== 2) {
    throw new Error("Clearing filters failed");
  }

  // Step 5: Test manual marker
  const manualTitle = manualForm.querySelector('[name="title"]');
  const manualStreamer = manualForm.querySelector('[name="streamer"]');
  const manualGame = manualForm.querySelector('[name="game"]');
  const manualCategory = manualForm.querySelector('[name="category"]');
  const manualDescription = manualForm.querySelector('[name="description"]');

  manualTitle.value = "Manual Highlight";
  manualStreamer.value = "ManualStreamer";
  manualGame.value = "ManualGame";
  manualCategory.value = "ManualCategory";
  manualDescription.value = "This is a manually added highlight";

  manualForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  await new Promise(resolve => setTimeout(resolve, 500));

  const manualCard = Array.from(recordsContainer.querySelectorAll('.highlight-card')).find(card =>
    card.querySelector('.highlight-title').textContent.includes("Manual Highlight")
  );

  if (!manualCard) throw new Error("Manual marker was not added to the visible list");

  const storedRecords = JSON.parse(localStorage.getItem('cgnk.streamerHighlightFinder.records') || "[]");
  if (!storedRecords.some(record => record.title === "Manual Highlight")) {
    throw new Error("Manual marker was not saved to localStorage");
  }

  // Step 6: Test export
  const originalCreateObjectURL = URL.createObjectURL;
  let exportTriggered = false;

  URL.createObjectURL = function(blob) {
    exportTriggered = true;
    return originalCreateObjectURL(blob);
  };

  exportButton.click();

  await new Promise(resolve => setTimeout(resolve, 500));

  URL.createObjectURL = originalCreateObjectURL;

  if (!exportTriggered) throw new Error("Export action was not triggered");

  return { status: 'pass' };
};