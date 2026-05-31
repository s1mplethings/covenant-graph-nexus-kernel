window.runSmokeTest = async function () {
  const result = {
    importTest: false,
    scoringTest: false,
    sortingTest: false,
    filteringTest: false,
    manualMarkerTest: false,
    localStorageTest: false,
    exportTest: false,
    errors: []
  };

  try {
    // Step 1: Import sample data through textarea
    const sampleData = JSON.stringify([
      {
        streamer: "Streamer1",
        game: "Game1",
        timestamp: "2023-10-01T12:00:00Z",
        time: "12:00:00",
        category: "Action",
        intensity: 8,
        chatRate: 15,
        keywords: ["kill", "win"],
        title: "Epic Kill",
        description: "An amazing kill moment",
        score: 0
      },
      {
        streamer: "Streamer2",
        game: "Game2",
        timestamp: "2023-10-01T12:05:00Z",
        time: "12:05:00",
        category: "Strategy",
        intensity: 5,
        chatRate: 10,
        keywords: ["strategy", "win"],
        title: "Strategic Win",
        description: "A brilliant strategy moment",
        score: 0
      }
    ]);

    const textarea = document.getElementById("json-textarea");
    const importButton = document.getElementById("import-button");
    textarea.value = sampleData;
    importButton.click();

    // Verify data was imported and rendered
    const recordsContainer = document.getElementById("records-container");
    if (recordsContainer && recordsContainer.children.length === 2) {
      result.importTest = true;
    } else {
      throw new Error("Import test failed: Records not rendered correctly.");
    }

    // Step 2: Verify scoring and sorting
    const records = Array.from(recordsContainer.children);
    const scores = records.map(record => parseFloat(record.querySelector(".score").textContent));
    if (scores[0] >= scores[1]) {
      result.scoringTest = true;
      result.sortingTest = true;
    } else {
      throw new Error("Scoring or sorting test failed: Scores not calculated or sorted correctly.");
    }

    // Step 3: Verify filtering
    const filterForm = document.getElementById("filter-form");
    const filterStreamer = document.getElementById("filterStreamer");
    filterStreamer.value = "Streamer1";
    filterForm.dispatchEvent(new Event("submit"));

    const filteredRecords = Array.from(recordsContainer.children);
    if (filteredRecords.length === 1 && filteredRecords[0].querySelector(".streamer").textContent === "Streamer1") {
      result.filteringTest = true;
    } else {
      throw new Error("Filtering test failed: Records not filtered correctly.");
    }

    // Step 4: Verify manual marker
    const manualForm = document.getElementById("manual-form");
    const manualData = {
      streamer: "Streamer3",
      game: "Game3",
      timestamp: "2023-10-01T12:10:00Z",
      time: "12:10:00",
      category: "Adventure",
      intensity: 7,
      chatRate: 12,
      keywords: ["adventure", "explore"],
      title: "Adventure Moment",
      description: "An exciting adventure moment",
      score: 0
    };

    Object.keys(manualData).forEach(key => {
      const input = manualForm.querySelector(`[name="${key}"]`);
      if (input) input.value = manualData[key];
    });
    manualForm.dispatchEvent(new Event("submit"));

    const updatedRecords = Array.from(recordsContainer.children);
    if (updatedRecords.length === 2 && updatedRecords.some(record => record.querySelector(".streamer").textContent === "Streamer3")) {
      result.manualMarkerTest = true;
    } else {
      throw new Error("Manual marker test failed: Record not added correctly.");
    }

    // Step 5: Verify localStorage persistence
    const localStorageKey = "cgnk.streamerHighlightFinder.records";
    const storedData = JSON.parse(localStorage.getItem(localStorageKey));
    if (storedData && storedData.length === 2) {
      result.localStorageTest = true;
    } else {
      throw new Error("LocalStorage test failed: Data not persisted correctly.");
    }

    // Step 6: Verify export functionality
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

    exportButton.click();

    if (exportTriggered) {
      result.exportTest = true;
    } else {
      throw new Error("Export test failed: Export action not triggered.");
    }

    // Restore original Blob and URL.createObjectURL
    window.Blob = originalBlob;
    window.URL.createObjectURL = originalCreateObjectURL;

  } catch (error) {
    result.errors.push(error.message);
  }

  return result;
};