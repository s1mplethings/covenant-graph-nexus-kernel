window.runSmokeTest = async function () {
  // Helper function to extract numeric score from .score-badge
  const extractScore = (element) => {
    const match = element.textContent.match(/\d+/);
    if (!match) throw new Error("Invalid score badge content");
    const score = parseInt(match[0], 10);
    if (isNaN(score) || score <= 0) throw new Error("Score must be numeric and positive");
    return score;
  };

  // Helper function to verify sorting order
  const verifySorting = (cards) => {
    let previousScore = Infinity;
    for (const card of cards) {
      const scoreBadge = card.querySelector(".score-badge");
      if (!scoreBadge) throw new Error("Missing .score-badge in result card");
      const score = extractScore(scoreBadge);
      if (score > previousScore) throw new Error("Cards are not sorted in descending order by score");
      previousScore = score;
    }
  };

  // Step 1: Import sample data
  const jsonTextarea = document.getElementById("json-textarea");
  const importButton = document.getElementById("import-button");
  if (!jsonTextarea || !importButton) throw new Error("Missing import controls");

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
      title: "Highlight 1",
      description: "Description 1",
      score: 0 // Score will be computed by the app
    },
    {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-10-01T12:05:00Z",
      time: "12:05 PM",
      category: "Category2",
      intensity: 8,
      chatRate: 15,
      keywords: ["keyword3", "keyword4"],
      title: "Highlight 2",
      description: "Description 2",
      score: 0 // Score will be computed by the app
    }
  ]);

  jsonTextarea.value = sampleData;
  importButton.click();

  // Step 2: Verify imported records are rendered correctly
  const recordsContainer = document.getElementById("records-container");
  if (!recordsContainer) throw new Error("Missing records container");

  const cards = Array.from(recordsContainer.querySelectorAll(".highlight-card"));
  if (cards.length !== 2) throw new Error("Expected 2 highlight cards after import");

  for (const card of cards) {
    const title = card.querySelector(".highlight-title");
    const streamer = card.querySelector(".metadata-streamer");
    const game = card.querySelector(".metadata-game");
    const time = card.querySelector(".metadata-time");
    const category = card.querySelector(".metadata-category");
    const description = card.querySelector(".highlight-description");

    if (!title || !streamer || !game || !time || !category || !description) {
      throw new Error("Missing required fields in result card");
    }
  }

  verifySorting(cards);

  // Step 3: Test filtering functionality
  const filterForm = document.getElementById("filter-form");
  const filterStreamer = document.getElementById("filterStreamer");
  const filterGame = document.getElementById("filterGame");
  const filterCategory = document.getElementById("filterCategory");
  const filterScore = document.getElementById("filterScore");
  if (!filterForm || !filterStreamer || !filterGame || !filterCategory || !filterScore) {
    throw new Error("Missing filter controls");
  }

  filterStreamer.value = "Streamer1";
  filterForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

  const filteredCards = Array.from(recordsContainer.querySelectorAll(".highlight-card"));
  if (filteredCards.length !== 1) throw new Error("Expected 1 card after filtering by streamer");
  if (!filteredCards[0].querySelector(".metadata-streamer").textContent.includes("Streamer1")) {
    throw new Error("Filtered card does not match streamer filter");
  }

  // Clear filters
  filterStreamer.value = "";
  filterGame.value = "";
  filterCategory.value = "";
  filterScore.value = "";
  filterForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

  // Step 4: Test manual marker functionality
  const manualForm = document.getElementById("manual-form");
  if (!manualForm) throw new Error("Missing manual marker form");

  const manualTitle = manualForm.querySelector("[name='title']");
  const manualStreamer = manualForm.querySelector("[name='streamer']");
  const manualGame = manualForm.querySelector("[name='game']");
  const manualCategory = manualForm.querySelector("[name='category']");
  const manualDescription = manualForm.querySelector("[name='description']");
  if (!manualTitle || !manualStreamer || !manualGame || !manualCategory || !manualDescription) {
    throw new Error("Missing manual marker fields");
  }

  manualTitle.value = "Manual Highlight";
  manualStreamer.value = "Manual Streamer";
  manualGame.value = "Manual Game";
  manualCategory.value = "Manual Category";
  manualDescription.value = "Manual Description";
  manualForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

  const updatedCards = Array.from(recordsContainer.querySelectorAll(".highlight-card"));
  const manualCard = updatedCards.find((card) =>
    card.querySelector(".highlight-title").textContent.includes("Manual Highlight")
  );
  if (!manualCard) throw new Error("Manual marker was not added to the visible result list");

  const localStorageData = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
  if (!localStorageData.some((record) => record.title === "Manual Highlight")) {
    throw new Error("Manual marker was not saved to localStorage");
  }

  // Step 5: Test export functionality
  const exportButton = document.getElementById("export-button");
  if (!exportButton) throw new Error("Missing export button");

  const originalCreateObjectURL = URL.createObjectURL;
  let blobTriggered = false;
  URL.createObjectURL = (blob) => {
    blobTriggered = true;
    return originalCreateObjectURL(blob);
  };

  exportButton.click();
  URL.createObjectURL = originalCreateObjectURL;

  if (!blobTriggered) throw new Error("Export functionality did not trigger a Blob download");

  return { status: "pass" };
};