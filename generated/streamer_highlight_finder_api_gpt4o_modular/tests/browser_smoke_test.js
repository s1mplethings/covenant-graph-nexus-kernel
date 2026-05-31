window.runSmokeTest = async function () {
  const result = {
    dataImport: false,
    scoring: false,
    filtering: false,
    manualMarker: false,
    export: false,
    localStorage: false,
    errors: []
  };

  try {
    // Step 1: Import sample data through textarea
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
      },
      {
        streamer: "Streamer2",
        game: "Game2",
        timestamp: "2023-01-01T13:00:00Z",
        time: "13:00:00",
        category: "Strategy",
        intensity: 5,
        chatRate: 10,
        keywords: ["strategic", "win"],
        title: "Strategic Win",
        description: "A strategic win in the game.",
        score: 0
      }
    ]);

    const textarea = document.getElementById("json-textarea");
    const importButton = document.getElementById("import-button");
    textarea.value = sampleData;
    importButton.click();

    // Wait for data to be processed
    await new Promise((resolve) => setTimeout(resolve, 1000));

    const recordsContainer = document.getElementById("records-container");
    if (recordsContainer.children.length > 0) {
      result.dataImport = true;
    } else {
      throw new Error("Data import failed: No records displayed.");
    }

    // Step 2: Verify scoring and sorting
    const records = Array.from(recordsContainer.children).map((child) => ({
      score: parseFloat(child.getAttribute("data-score"))
    }));

    if (
      records.length > 0 &&
      records.every((record, index, arr) =>
        index === 0 ? true : record.score <= arr[index - 1].score
      )
    ) {
      result.scoring = true;
    } else {
      throw new Error("Scoring or sorting failed: Records are not sorted by score.");
    }

    // Step 3: Test filtering
    const filterForm = document.getElementById("filter-form");
    const filterStreamer = document.getElementById("filterStreamer");
    filterStreamer.value = "Streamer1";
    filterForm.dispatchEvent(new Event("submit"));

    await new Promise((resolve) => setTimeout(resolve, 500));

    const filteredRecords = Array.from(recordsContainer.children);
    if (
      filteredRecords.length > 0 &&
      filteredRecords.every((child) => child.getAttribute("data-streamer") === "Streamer1")
    ) {
      result.filtering = true;
    } else {
      throw new Error("Filtering failed: Records do not match filter criteria.");
    }

    // Step 4: Test manual marker
    const manualForm = document.getElementById("manual-form");
    const newRecord = {
      streamer: "Streamer3",
      game: "Game3",
      timestamp: "2023-01-01T14:00:00Z",
      time: "14:00:00",
      category: "Adventure",
      intensity: 7,
      chatRate: 12,
      keywords: ["adventure", "fun"],
      title: "Fun Adventure",
      description: "A fun adventure in the game.",
      score: 0
    };

    Object.keys(newRecord).forEach((key) => {
      const input = manualForm.querySelector(`[name="${key}"]`);
      if (input) input.value = newRecord[key];
    });

    manualForm.dispatchEvent(new Event("submit"));

    await new Promise((resolve) => setTimeout(resolve, 500));

    const updatedRecords = Array.from(recordsContainer.children);
    if (
      updatedRecords.some(
        (child) => child.getAttribute("data-streamer") === "Streamer3"
      )
    ) {
      result.manualMarker = true;
    } else {
      throw new Error("Manual marker failed: New record not added.");
    }

    // Step 5: Test export functionality
    const exportButton = document.getElementById("export-button");
    exportButton.click();

    await new Promise((resolve) => setTimeout(resolve, 500));

    const downloadLink = document.querySelector("a[download]");
    if (downloadLink && downloadLink.href) {
      result.export = true;
    } else {
      throw new Error("Export failed: No download link generated.");
    }

    // Step 6: Test localStorage persistence
    const savedData = JSON.parse(localStorage.getItem("highlightData"));
    if (savedData && savedData.length > 0) {
      result.localStorage = true;
    } else {
      throw new Error("LocalStorage persistence failed: No data saved.");
    }
  } catch (error) {
    result.errors.push(error.message);
  }

  return result;
};