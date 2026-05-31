window.runSmokeTest = async function () {
  const localStorageKey = "cgnk.streamerHighlightFinder.records";

  // Helper functions
  const waitForRender = () => new Promise((resolve) => setTimeout(resolve, 100)); // Wait for UI updates
  const getVisibleRecords = () => {
    const container = document.getElementById("records-container");
    return Array.from(container.querySelectorAll(".highlight-card")).map((card) => ({
      title: card.querySelector(".highlight-title")?.textContent.trim(),
      streamer: card.querySelector(".metadata-streamer")?.textContent.trim(),
      game: card.querySelector(".metadata-game")?.textContent.trim(),
      time: card.querySelector(".metadata-time")?.textContent.trim(),
      category: card.querySelector(".metadata-category")?.textContent.trim(),
      score: card.querySelector(".score-badge")?.textContent.trim(),
      description: card.querySelector(".highlight-description")?.textContent.trim(),
    }));
  };

  const assertVisibleRecordFields = (record) => {
    const requiredFields = ["title", "streamer", "game", "time", "category", "score", "description"];
    requiredFields.forEach((field) => {
      if (!record[field]) {
        throw new Error(`Missing visible field "${field}" in record: ${JSON.stringify(record)}`);
      }
    });
  };

  const assertLocalStorageContainsRecord = (record) => {
    const storedRecords = JSON.parse(localStorage.getItem(localStorageKey) || "[]");
    const match = storedRecords.find((r) => r.title === record.title && r.streamer === record.streamer);
    if (!match) {
      throw new Error(`Record not found in localStorage: ${JSON.stringify(record)}`);
    }
  };

  const clearFilters = () => {
    document.getElementById("filterStreamer").value = "";
    document.getElementById("filterGame").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterScore").value = "";
    document.getElementById("filter-form").dispatchEvent(new Event("submit"));
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
      title: "Highlight 1",
      description: "Description of Highlight 1",
      score: 95,
    },
    {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-10-01T13:00:00Z",
      time: "1:00 PM",
      category: "Category2",
      intensity: 3,
      chatRate: 5,
      keywords: ["keyword3", "keyword4"],
      title: "Highlight 2",
      description: "Description of Highlight 2",
      score: 80,
    },
  ]);

  const textarea = document.getElementById("json-textarea");
  const importButton = document.getElementById("import-button");
  textarea.value = sampleData;
  importButton.click();
  await waitForRender();

  // Step 2: Verify imported records are visible
  const visibleRecords = getVisibleRecords();
  if (visibleRecords.length !== 2) {
    throw new Error(`Expected 2 records, but found ${visibleRecords.length}`);
  }
  visibleRecords.forEach(assertVisibleRecordFields);

  // Step 3: Test filtering
  document.getElementById("filterStreamer").value = "Streamer1";
  document.getElementById("filter-form").dispatchEvent(new Event("submit"));
  await waitForRender();

  const filteredRecords = getVisibleRecords();
  if (filteredRecords.length !== 1 || filteredRecords[0].streamer !== "Streamer1") {
    throw new Error("Filtering by streamer failed");
  }

  clearFilters();
  await waitForRender();

  // Step 4: Test manual marker
  const manualForm = document.getElementById("manual-form");
  manualForm.querySelector("[name='title']").value = "Manual Highlight";
  manualForm.querySelector("[name='streamer']").value = "Manual Streamer";
  manualForm.querySelector("[name='game']").value = "Manual Game";
  manualForm.querySelector("[name='category']").value = "Manual Category";
  manualForm.querySelector("[name='score']").value = "100";
  manualForm.querySelector("[name='description']").value = "Manual Description";
  manualForm.dispatchEvent(new Event("submit"));
  await waitForRender();

  const manualRecord = {
    title: "Manual Highlight",
    streamer: "Manual Streamer",
    game: "Manual Game",
    category: "Manual Category",
    score: "100",
    description: "Manual Description",
  };

  const updatedRecords = getVisibleRecords();
  const manualVisible = updatedRecords.find((r) => r.title === manualRecord.title);
  if (!manualVisible) {
    throw new Error("Manual marker record not visible");
  }
  assertLocalStorageContainsRecord(manualRecord);

  // Step 5: Test export functionality
  const exportButton = document.getElementById("export-button");
  const originalCreateObjectURL = URL.createObjectURL;
  let blobTriggered = false;

  URL.createObjectURL = (blob) => {
    blobTriggered = true;
    return originalCreateObjectURL(blob);
  };

  exportButton.click();
  await waitForRender();

  URL.createObjectURL = originalCreateObjectURL;
  if (!blobTriggered) {
    throw new Error("Export functionality did not trigger Blob creation");
  }

  console.log("Smoke test passed!");
};