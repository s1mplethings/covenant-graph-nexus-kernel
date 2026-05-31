window.runSmokeTest = async function () {
  console.log("Starting smoke test...");

  // Helper function to wait for DOM updates
  const waitForDOMUpdate = (timeout = 100) => new Promise(resolve => setTimeout(resolve, timeout));

  // Step 1: Import sample data
  const sampleData = JSON.stringify([
    {
      "streamer": "Streamer1",
      "game": "Game1",
      "timestamp": "2023-01-01T12:00:00Z",
      "time": "12:00 PM",
      "category": "Category1",
      "intensity": 80,
      "chatRate": 50,
      "keywords": ["exciting", "clutch"],
      "title": "Epic Moment",
      "description": "An amazing play happened here.",
      "score": 0 // Score will be recalculated
    },
    {
      "streamer": "Streamer2",
      "game": "Game2",
      "timestamp": "2023-01-01T13:00:00Z",
      "time": "1:00 PM",
      "category": "Category2",
      "intensity": 90,
      "chatRate": 70,
      "keywords": ["intense", "highlight"],
      "title": "Clutch Play",
      "description": "A clutch play that turned the game around.",
      "score": 0 // Score will be recalculated
    }
  ]);

  const jsonTextarea = document.getElementById("json-textarea");
  const importButton = document.getElementById("import-button");

  if (!jsonTextarea || !importButton) {
    console.error("Import controls not found.");
    return;
  }

  jsonTextarea.value = sampleData;
  importButton.click();

  await waitForDOMUpdate();

  // Step 2: Verify imported records are rendered correctly
  const recordsContainer = document.getElementById("records-container");
  if (!recordsContainer) {
    console.error("Records container not found.");
    return;
  }

  const cards = recordsContainer.querySelectorAll(".highlight-card");
  if (cards.length !== 2) {
    console.error(`Expected 2 highlight cards, but found ${cards.length}.`);
    return;
  }

  cards.forEach(card => {
    const title = card.querySelector(".highlight-title");
    const streamer = card.querySelector(".metadata-streamer");
    const game = card.querySelector(".metadata-game");
    const category = card.querySelector(".metadata-category");
    const scoreBadge = card.querySelector(".score-badge");
    const description = card.querySelector(".highlight-description");

    if (!title || !streamer || !game || !category || !scoreBadge || !description) {
      console.error("One or more required fields are missing in a highlight card.");
      return;
    }

    const score = parseFloat(scoreBadge.textContent);
    if (isNaN(score) || score <= 0) {
      console.error("Invalid score detected:", score);
      return;
    }
  });

  console.log("Imported records are rendered correctly.");

  // Step 3: Verify sorting by score (descending)
  const scores = Array.from(cards).map(card => parseFloat(card.querySelector(".score-badge").textContent));
  if (!scores.every((score, i, arr) => i === 0 || arr[i - 1] >= score)) {
    console.error("Records are not sorted by score in descending order.");
    return;
  }

  console.log("Records are sorted by score in descending order.");

  // Step 4: Test filtering functionality
  const filterForm = document.getElementById("filter-form");
  const filterStreamer = document.getElementById("filterStreamer");
  const filterGame = document.getElementById("filterGame");
  const filterCategory = document.getElementById("filterCategory");
  const filterScore = document.getElementById("filterScore");

  if (!filterForm || !filterStreamer || !filterGame || !filterCategory || !filterScore) {
    console.error("Filter controls not found.");
    return;
  }

  filterStreamer.value = "Streamer1";
  filterForm.submit();

  await waitForDOMUpdate();

  const filteredCards = recordsContainer.querySelectorAll(".highlight-card");
  if (filteredCards.length !== 1 || !filteredCards[0].querySelector(".metadata-streamer").textContent.includes("Streamer1")) {
    console.error("Filtering by streamer failed.");
    return;
  }

  console.log("Filtering by streamer works correctly.");

  // Clear filters
  filterStreamer.value = "";
  filterGame.value = "";
  filterCategory.value = "";
  filterScore.value = "";
  filterForm.submit();

  await waitForDOMUpdate();

  // Step 5: Test manual marker functionality
  const manualForm = document.getElementById("manual-form");
  if (!manualForm) {
    console.error("Manual marker form not found.");
    return;
  }

  const manualTitle = manualForm.querySelector("[name='title']");
  const manualStreamer = manualForm.querySelector("[name='streamer']");
  const manualGame = manualForm.querySelector("[name='game']");
  const manualCategory = manualForm.querySelector("[name='category']");
  const manualDescription = manualForm.querySelector("[name='description']");

  if (!manualTitle || !manualStreamer || !manualGame || !manualCategory || !manualDescription) {
    console.error("Manual marker form fields not found.");
    return;
  }

  manualTitle.value = "New Highlight";
  manualStreamer.value = "NewStreamer";
  manualGame.value = "NewGame";
  manualCategory.value = "NewCategory";
  manualDescription.value = "This is a manually added highlight.";
  manualForm.submit();

  await waitForDOMUpdate();

  const newCard = Array.from(recordsContainer.querySelectorAll(".highlight-card")).find(card =>
    card.querySelector(".highlight-title").textContent.includes("New Highlight")
  );

  if (!newCard) {
    console.error("Manual marker was not added to the visible result list.");
    return;
  }

  const localStorageKey = "cgnk.streamerHighlightFinder.records";
  const storedRecords = JSON.parse(localStorage.getItem(localStorageKey) || "[]");
  if (!storedRecords.some(record => record.title === "New Highlight" && record.streamer === "NewStreamer")) {
    console.error("Manual marker was not saved to localStorage.");
    return;
  }

  console.log("Manual marker functionality works correctly.");

  // Step 6: Test export functionality
  const exportButton = document.getElementById("export-button");
  if (!exportButton) {
    console.error("Export button not found.");
    return;
  }

  const originalCreateObjectURL = URL.createObjectURL;
  let exportTriggered = false;

  URL.createObjectURL = function (blob) {
    exportTriggered = true;
    return originalCreateObjectURL(blob);
  };

  exportButton.click();

  await waitForDOMUpdate();

  URL.createObjectURL = originalCreateObjectURL;

  if (!exportTriggered) {
    console.error("Export functionality did not trigger a download.");
    return;
  }

  console.log("Export functionality works correctly.");

  console.log("Smoke test completed successfully.");
};