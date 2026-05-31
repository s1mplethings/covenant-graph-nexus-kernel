window.runSmokeTest = async function () {
  const localStorageKey = "cgnk.streamerHighlightFinder.records";

  const result = {
    importTest: false,
    scoringTest: false,
    sortingTest: false,
    filteringTest: false,
    manualMarkerTest: false,
    localStorageTest: false,
    exportTest: false,
    errors: [],
  };

  try {
    // Step 1: Import sample data through textarea
    const sampleData = [
      {
        streamer: "Streamer1",
        game: "GameA",
        timestamp: "2023-10-01T12:00:00Z",
        time: "12:00:00",
        category: "Action",
        intensity: 8,
        chatRate: 15,
        keywords: ["exciting", "boss fight"],
        title: "Epic Boss Fight",
        description: "Streamer1 defeats the final boss in GameA.",
        score: 0,
      },
      {
        streamer: "Streamer2",
        game: "GameB",
        timestamp: "2023-10-01T13:00:00Z",
        time: "13:00:00",
        category: "Strategy",
        intensity: 5,
        chatRate: 10,
        keywords: ["strategy", "planning"],
        title: "Strategic Victory",
        description: "Streamer2 wins a strategic match in GameB.",
        score: 0,
      },
    ];

    const textarea = document.getElementById("json-textarea");
    textarea.value = JSON.stringify(sampleData);

    const importButton = document.getElementById("import-button");
    importButton.click();

    const importedRecords = JSON.parse(localStorage.getItem(localStorageKey));
    if (importedRecords && importedRecords.length === sampleData.length) {
      result.importTest = true;
    } else {
      result.errors.push("Import test failed: Records not imported correctly.");
    }

    // Step 2: Verify scoring and sorting
    const scoreRecord = (record) => {
      return record.intensity * 2 + record.chatRate;
    };

    importedRecords.forEach((record) => {
      record.score = scoreRecord(record);
    });

    const sortedRecords = [...importedRecords].sort((a, b) => b.score - a.score);
    if (
      sortedRecords[0].score >= sortedRecords[1].score &&
      sortedRecords[0].score > 0
    ) {
      result.scoringTest = true;
      result.sortingTest = true;
    } else {
      result.errors.push("Scoring or sorting test failed.");
    }

    // Step 3: Verify filtering
    const filterForm = document.getElementById("filter-form");
    const filterStreamer = document.getElementById("filterStreamer");
    filterStreamer.value = "Streamer1";
    filterForm.dispatchEvent(new Event("submit"));

    const filteredRecords = JSON.parse(localStorage.getItem(localStorageKey));
    if (
      filteredRecords.length === 1 &&
      filteredRecords[0].streamer === "Streamer1"
    ) {
      result.filteringTest = true;
    } else {
      result.errors.push("Filtering test failed.");
    }

    // Step 4: Verify manual marker
    const manualForm = document.getElementById("manual-form");
    const newRecord = {
      streamer: "Streamer3",
      game: "GameC",
      timestamp: "2023-10-01T14:00:00Z",
      time: "14:00:00",
      category: "Adventure",
      intensity: 7,
      chatRate: 12,
      keywords: ["exploration", "discovery"],
      title: "Exploration Adventure",
      description: "Streamer3 explores new areas in GameC.",
      score: 0,
    };

    Object.keys(newRecord).forEach((key) => {
      const input = manualForm.querySelector(`[name="${key}"]`);
      if (input) input.value = newRecord[key];
    });

    manualForm.dispatchEvent(new Event("submit"));

    const updatedRecords = JSON.parse(localStorage.getItem(localStorageKey));
    if (
      updatedRecords.some(
        (record) =>
          record.streamer === "Streamer3" &&
          record.title === "Exploration Adventure"
      )
    ) {
      result.manualMarkerTest = true;
    } else {
      result.errors.push("Manual marker test failed.");
    }

    // Step 5: Verify localStorage persistence
    localStorage.setItem(localStorageKey, JSON.stringify(updatedRecords));
    const reloadedRecords = JSON.parse(localStorage.getItem(localStorageKey));
    if (JSON.stringify(reloadedRecords) === JSON.stringify(updatedRecords)) {
      result.localStorageTest = true;
    } else {
      result.errors.push("LocalStorage test failed.");
    }

    // Step 6: Verify export functionality
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

    const exportButton = document.getElementById("export-button");
    exportButton.click();

    if (exportTriggered) {
      result.exportTest = true;
    } else {
      result.errors.push("Export test failed: Blob or URL.createObjectURL not triggered.");
    }

    // Restore original Blob and URL.createObjectURL
    window.Blob = originalBlob;
    window.URL.createObjectURL = originalCreateObjectURL;

  } catch (error) {
    result.errors.push(`Unexpected error: ${error.message}`);
  }

  return result;
};