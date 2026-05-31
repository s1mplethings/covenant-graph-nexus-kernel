window.runSmokeTest = async function () {
  const localStorageKey = "cgnk.streamerHighlightFinder.records";

  // Helper function to wait for DOM updates
  const waitFor = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // Helper function to verify visible text in result cards
  const verifyResultCard = (card) => {
    const requiredClasses = [
      "highlight-title",
      "metadata-streamer",
      "metadata-game",
      "metadata-time",
      "metadata-category",
      "highlight-description",
      "score-badge",
    ];
    return requiredClasses.every((cls) => card.querySelector(`.${cls}`));
  };

  // Step 1: Import sample data
  const sampleData = JSON.stringify([
    {
      streamer: "Streamer1",
      game: "Game1",
      timestamp: "2023-10-01T12:00:00Z",
      time: "12:00 PM",
      category: "Category1",
      intensity: 5,
      chatRate: 10,
      keywords: ["keyword1", "keyword2"],
      title: "Highlight Title 1",
      description: "Description of highlight 1",
      score: 85,
    },
    {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-10-01T13:00:00Z",
      time: "1:00 PM",
      category: "Category2",
      intensity: 8,
      chatRate: 15,
      keywords: ["keyword3", "keyword4"],
      title: "Highlight Title 2",
      description: "Description of highlight 2",
      score: 90,
    },
  ]);

  const textarea = document.getElementById("json-textarea");
  const importButton = document.getElementById("import-button");

  if (!textarea || !importButton) {
    console.error("Import controls not found.");
    return false;
  }

  textarea.value = sampleData;
  importButton.click();

  await waitFor(500); // Wait for import processing

  // Step 2: Verify imported records are rendered correctly
  const recordsContainer = document.getElementById("records-container");
  if (!recordsContainer) {
    console.error("Records container not found.");
    return false;
  }

  const resultCards = recordsContainer.querySelectorAll(".highlight-card");
  if (resultCards.length !== 2) {
    console.error("Incorrect number of result cards rendered.");
    return false;
  }

  for (const card of resultCards) {
    if (!verifyResultCard(card)) {
      console.error("Result card missing required fields.");
      return false;
    }
  }

  // Step 3: Test filtering functionality
  const filterForm = document.getElementById("filter-form");
  const filterStreamer = document.getElementById("filterStreamer");
  const filterGame = document.getElementById("filterGame");
  const filterCategory = document.getElementById("filterCategory");
  const filterScore = document.getElementById("filterScore");

  if (!filterForm || !filterStreamer || !filterGame || !filterCategory || !filterScore) {
    console.error("Filter controls not found.");
    return false;
  }

  filterStreamer.value = "Streamer1";
  filterForm.dispatchEvent(new Event("submit"));

  await waitFor(500); // Wait for filtering

  const filteredCards = recordsContainer.querySelectorAll(".highlight-card");
  if (filteredCards.length !== 1 || !filteredCards[0].querySelector(".metadata-streamer").textContent.includes("Streamer1")) {
    console.error("Filtering by streamer failed.");
    return false;
  }

  // Step 4: Test manual marker functionality
  const manualForm = document.getElementById("manual-form");
  if (!manualForm) {
    console.error("Manual marker form not found.");
    return false;
  }

  const manualData = {
    streamer: "Streamer3",
    game: "Game3",
    timestamp: "2023-10-01T14:00:00Z",
    time: "2:00 PM",
    category: "Category3",
    intensity: 7,
    chatRate: 12,
    keywords: ["keyword5", "keyword6"],
    title: "Highlight Title 3",
    description: "Description of highlight 3",
    score: 88,
  };

  for (const key in manualData) {
    const input = manualForm.querySelector(`[name="${key}"]`);
    if (input) {
      input.value = manualData[key];
    }
  }

  manualForm.dispatchEvent(new Event("submit"));

  await waitFor(500); // Wait for manual marker processing

  const updatedCards = recordsContainer.querySelectorAll(".highlight-card");
  if (updatedCards.length !== 3 || !updatedCards[2].querySelector(".metadata-streamer").textContent.includes("Streamer3")) {
    console.error("Manual marker failed.");
    return false;
  }

  // Step 5: Test export functionality
  const exportButton = document.getElementById("export-button");
  if (!exportButton) {
    console.error("Export button not found.");
    return false;
  }

  let exportTriggered = false;
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = (blob) => {
    exportTriggered = true;
    return originalCreateObjectURL(blob);
  };

  exportButton.click();

  await waitFor(500); // Wait for export processing

  URL.createObjectURL = originalCreateObjectURL; // Restore original function

  if (!exportTriggered) {
    console.error("Export functionality failed.");
    return false;
  }

  // Step 6: Verify localStorage persistence
  const savedRecords = JSON.parse(localStorage.getItem(localStorageKey));
  if (!savedRecords || savedRecords.length !== 3) {
    console.error("LocalStorage persistence failed.");
    return false;
  }

  console.log("Smoke test passed!");
  return true;
};