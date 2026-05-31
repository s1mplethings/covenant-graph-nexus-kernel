window.runSmokeTest = async function () {
  const result = {
    importTest: false,
    scoringTest: false,
    filteringTest: false,
    manualMarkerTest: false,
    exportTest: false,
    localStorageTest: false,
    errors: []
  };

  try {
    // Step 1: Import JSON data through textarea
    const textarea = document.getElementById('json-textarea');
    const importButton = document.getElementById('import-button');
    const sampleData = JSON.stringify([
      {
        streamer: "Streamer1",
        game: "Game1",
        timestamp: "2023-01-01T12:00:00Z",
        time: "12:00:00",
        category: "Action",
        intensity: 8,
        chatRate: 15,
        keywords: ["exciting", "clutch"],
        title: "Epic Moment",
        description: "An epic moment in the game.",
        score: 0
      }
    ]);

    textarea.value = sampleData;
    importButton.click();

    const recordsContainer = document.getElementById('records-container');
    if (recordsContainer && recordsContainer.innerText.includes("Streamer1")) {
      result.importTest = true;
    } else {
      throw new Error("Import test failed: Data not rendered in UI.");
    }

    // Step 2: Verify scoring and sorting
    const records = JSON.parse(localStorage.getItem('cgnk.streamerHighlightFinder.records'));
    if (records && records[0].score > 0) {
      result.scoringTest = true;
    } else {
      throw new Error("Scoring test failed: Scores not calculated or incorrect.");
    }

    // Step 3: Apply filters and verify
    const filterForm = document.getElementById('filter-form');
    const filterStreamer = document.getElementById('filterStreamer');
    filterStreamer.value = "Streamer1";
    filterForm.dispatchEvent(new Event('submit'));

    if (recordsContainer.innerText.includes("Streamer1")) {
      result.filteringTest = true;
    } else {
      throw new Error("Filtering test failed: Filter logic not applied correctly.");
    }

    // Step 4: Add manual highlight and verify
    const manualForm = document.getElementById('manual-form');
    const manualData = {
      streamer: "Streamer2",
      game: "Game2",
      timestamp: "2023-01-02T14:00:00Z",
      time: "14:00:00",
      category: "Adventure",
      intensity: 7,
      chatRate: 10,
      keywords: ["fun", "exploration"],
      title: "Exploration Moment",
      description: "A fun exploration moment.",
      score: 0
    };

    Object.keys(manualData).forEach(key => {
      const input = manualForm.querySelector(`[name="${key}"]`);
      if (input) input.value = manualData[key];
    });
    manualForm.dispatchEvent(new Event('submit'));

    if (recordsContainer.innerText.includes("Streamer2")) {
      result.manualMarkerTest = true;
    } else {
      throw new Error("Manual marker test failed: Manually added highlight not rendered.");
    }

    // Step 5: Export filtered results and verify
    const exportButton = document.getElementById('export-button');
    const originalCreateObjectURL = URL.createObjectURL;
    let exportTriggered = false;

    URL.createObjectURL = function (blob) {
      exportTriggered = true;
      return originalCreateObjectURL(blob);
    };

    exportButton.click();

    if (exportTriggered) {
      result.exportTest = true;
    } else {
      throw new Error("Export test failed: Export action not triggered.");
    }

    // Step 6: Verify localStorage persistence
    const reloadedRecords = JSON.parse(localStorage.getItem('cgnk.streamerHighlightFinder.records'));
    if (reloadedRecords && reloadedRecords.length > 0) {
      result.localStorageTest = true;
    } else {
      throw new Error("LocalStorage test failed: Data not persisted.");
    }

  } catch (error) {
    result.errors.push(error.message);
  }

  return result;
};