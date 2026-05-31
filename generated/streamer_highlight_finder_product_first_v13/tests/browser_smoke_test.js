window.runSmokeTest = async function () {
  const localStorageKey = "cgnk.streamerHighlightFinder.records";

  // Helper function to simulate a click event
  const simulateClick = (element) => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    element.dispatchEvent(event);
  };

  // Helper function to clear filters
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
      category: "Epic Moment",
      intensity: 8,
      chatRate: 120,
      keywords: ["amazing", "clutch"],
      title: "Amazing Clutch Play",
      description: "Streamer1 pulled off an incredible clutch play in Game1.",
      score: 95,
    },
    {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-10-01T13:00:00Z",
      time: "1:00 PM",
      category: "Funny Moment",
      intensity: 5,
      chatRate: 80,
      keywords: ["funny", "hilarious"],
      title: "Hilarious Fail",
      description: "Streamer2 had a hilarious fail in Game2.",
      score: 75,
    },
  ]);

  const jsonTextarea = document.getElementById("json-textarea");
  const importButton = document.getElementById("import-button");

  jsonTextarea.value = sampleData;
  simulateClick(importButton);

  // Step 2: Verify imported records are visible
  const recordsContainer = document.getElementById("records-container");
  const importedRecords = recordsContainer.querySelectorAll(".highlight-card");
  if (importedRecords.length !== 2) {
    throw new Error("Imported records are not visible.");
  }

  importedRecords.forEach((record, index) => {
    const data = JSON.parse(sampleData)[index];
    if (
      !record.querySelector(".highlight-title").textContent.includes(data.title) ||
      !record.querySelector(".metadata-streamer").textContent.includes(data.streamer) ||
      !record.querySelector(".metadata-game").textContent.includes(data.game) ||
      !record.querySelector(".metadata-category").textContent.includes(data.category) ||
      !record.querySelector(".score-badge").textContent.includes(data.score.toString()) ||
      !record.querySelector(".highlight-description").textContent.includes(data.description)
    ) {
      throw new Error(`Record ${index + 1} does not match expected data.`);
    }
  });

  // Step 3: Test filtering functionality
  const filterStreamer = document.getElementById("filterStreamer");
  const filterForm = document.getElementById("filter-form");

  filterStreamer.value = "Streamer1";
  filterForm.dispatchEvent(new Event("submit"));

  const filteredRecords = recordsContainer.querySelectorAll(".highlight-card");
  if (filteredRecords.length !== 1 || !filteredRecords[0].querySelector(".metadata-streamer").textContent.includes("Streamer1")) {
    throw new Error("Filtering by streamer failed.");
  }

  clearFilters();

  // Step 4: Test manual marker functionality
  const manualForm = document.getElementById("manual-form");
  const manualTitle = manualForm.querySelector("[name='title']");
  const manualStreamer = manualForm.querySelector("[name='streamer']");
  const manualGame = manualForm.querySelector("[name='game']");
  const manualCategory = manualForm.querySelector("[name='category']");
  const manualDescription = manualForm.querySelector("[name='description']");

  manualTitle.value = "New Highlight";
  manualStreamer.value = "Streamer3";
  manualGame.value = "Game3";
  manualCategory.value = "Epic Moment";
  manualDescription.value = "Streamer3 achieved something incredible.";

  manualForm.dispatchEvent(new Event("submit"));

  const updatedRecords = recordsContainer.querySelectorAll(".highlight-card");
  const newRecord = Array.from(updatedRecords).find((record) =>
    record.querySelector(".highlight-title").textContent.includes("New Highlight")
  );

  if (!newRecord) {
    throw new Error("Manual marker record is not visible.");
  }

  const storedRecords = JSON.parse(localStorage.getItem(localStorageKey));
  const storedNewRecord = storedRecords.find((record) => record.title === "New Highlight");

  if (!storedNewRecord || storedNewRecord.streamer !== "Streamer3") {
    throw new Error("Manual marker record is not stored in localStorage.");
  }

  // Step 5: Test export functionality
  const exportButton = document.getElementById("export-button");
  const originalBlob = window.Blob;
  const originalCreateObjectURL = window.URL.createObjectURL;

  let exportTriggered = false;

  window.Blob = function (data, options) {
    exportTriggered = true;
    return new originalBlob(data, options);
  };

  window.URL.createObjectURL = function (blob) {
    exportTriggered = true;
    return originalCreateObjectURL(blob);
  };

  simulateClick(exportButton);

  if (!exportTriggered) {
    throw new Error("Export functionality did not trigger.");
  }

  // Restore original Blob and URL.createObjectURL
  window.Blob = originalBlob;
  window.URL.createObjectURL = originalCreateObjectURL;

  console.log("Smoke test passed!");
};