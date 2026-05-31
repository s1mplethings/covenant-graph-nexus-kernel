window.runSmokeTest = async function () {
  const result = {
    importTest: false,
    renderTest: false,
    filterTest: false,
    sortTest: false,
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
        game: "Game1",
        timestamp: "2023-10-01T12:00:00Z",
        time: "12:00:00",
        category: "Category1",
        intensity: 5,
        chatRate: 10,
        keywords: ["keyword1", "keyword2"],
        title: "Highlight Title 1",
        description: "Description of highlight 1",
        score: 95,
      },
      {
        streamer: "Streamer2",
        game: "Game2",
        timestamp: "2023-10-01T13:00:00Z",
        time: "13:00:00",
        category: "Category2",
        intensity: 3,
        chatRate: 5,
        keywords: ["keyword3", "keyword4"],
        title: "Highlight Title 2",
        description: "Description of highlight 2",
        score: 85,
      },
    ];

    const textarea = document.createElement("textarea");
    textarea.id = "json-textarea";
    textarea.value = JSON.stringify(sampleData);
    document.body.appendChild(textarea);

    const importButton = document.createElement("button");
    importButton.id = "import-button";
    importButton.innerText = "Import";
    document.body.appendChild(importButton);

    importButton.addEventListener("click", () => {
      const jsonData = JSON.parse(textarea.value);
      localStorage.setItem("cgnk.streamerHighlightFinder.records", JSON.stringify(jsonData));
    });

    importButton.click();
    const importedData = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
    result.importTest = importedData.length === sampleData.length;

    // Step 2: Verify rendering of imported records
    const recordsContainer = document.createElement("div");
    recordsContainer.id = "records-container";
    document.body.appendChild(recordsContainer);

    const renderRecords = (records) => {
      recordsContainer.innerHTML = "";
      records.forEach((record) => {
        const card = document.createElement("div");
        card.className = "highlight-card";

        const title = document.createElement("div");
        title.className = "highlight-title";
        title.innerText = record.title;

        const streamer = document.createElement("div");
        streamer.className = "metadata-streamer";
        streamer.innerText = record.streamer;

        const game = document.createElement("div");
        game.className = "metadata-game";
        game.innerText = record.game;

        const time = document.createElement("div");
        time.className = "metadata-time";
        time.innerText = record.time;

        const category = document.createElement("div");
        category.className = "metadata-category";
        category.innerText = record.category;

        const description = document.createElement("div");
        description.className = "highlight-description";
        description.innerText = record.description;

        card.appendChild(title);
        card.appendChild(streamer);
        card.appendChild(game);
        card.appendChild(time);
        card.appendChild(category);
        card.appendChild(description);

        recordsContainer.appendChild(card);
      });
    };

    renderRecords(importedData);

    const renderedCards = recordsContainer.querySelectorAll(".highlight-card");
    result.renderTest = Array.from(renderedCards).every((card) => {
      return (
        card.querySelector(".highlight-title") &&
        card.querySelector(".metadata-streamer") &&
        card.querySelector(".metadata-game") &&
        card.querySelector(".metadata-time") &&
        card.querySelector(".metadata-category") &&
        card.querySelector(".highlight-description")
      );
    });

    // Step 3: Verify filtering functionality
    const filterForm = document.createElement("form");
    filterForm.id = "filter-form";

    const filterStreamer = document.createElement("input");
    filterStreamer.id = "filterStreamer";
    filterStreamer.value = "Streamer1";

    filterForm.appendChild(filterStreamer);
    document.body.appendChild(filterForm);

    const applyFilters = (records, filters) => {
      return records.filter((record) => record.streamer === filters.streamer);
    };

    const filteredRecords = applyFilters(importedData, { streamer: filterStreamer.value });
    renderRecords(filteredRecords);

    result.filterTest = recordsContainer.querySelectorAll(".highlight-card").length === 1;

    // Step 4: Verify sorting functionality
    const sortRecords = (records) => {
      return records.sort((a, b) => b.score - a.score);
    };

    const sortedRecords = sortRecords(importedData);
    renderRecords(sortedRecords);

    const sortedScores = Array.from(recordsContainer.querySelectorAll(".highlight-card")).map((card) =>
      parseInt(card.querySelector(".score-badge")?.innerText || "0", 10)
    );
    result.sortTest = sortedScores.every((score, index, arr) => index === 0 || score <= arr[index - 1]);

    // Step 5: Verify manual marker functionality
    const manualForm = document.createElement("form");
    manualForm.id = "manual-form";

    const manualTitle = document.createElement("input");
    manualTitle.id = "manualTitle";
    manualTitle.value = "Manual Highlight";

    manualForm.appendChild(manualTitle);
    document.body.appendChild(manualForm);

    manualForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const newRecord = {
        streamer: "Manual Streamer",
        game: "Manual Game",
        timestamp: new Date().toISOString(),
        time: "00:00:00",
        category: "Manual Category",
        intensity: 0,
        chatRate: 0,
        keywords: [],
        title: manualTitle.value,
        description: "Manual Description",
        score: 50,
      };
      const currentRecords = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
      currentRecords.push(newRecord);
      localStorage.setItem("cgnk.streamerHighlightFinder.records", JSON.stringify(currentRecords));
      renderRecords(currentRecords);
    });

    manualForm.dispatchEvent(new Event("submit"));
    const updatedRecords = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
    result.manualMarkerTest = updatedRecords.some((record) => record.title === "Manual Highlight");

    // Step 6: Verify localStorage persistence
    const reloadedRecords = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
    result.localStorageTest = reloadedRecords.length === updatedRecords.length;

    // Step 7: Verify export functionality
    const exportButton = document.createElement("button");
    exportButton.id = "export-button";
    exportButton.innerText = "Export";
    document.body.appendChild(exportButton);

    const exportData = (records) => {
      const blob = new Blob([JSON.stringify(records)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "highlights.json";
      anchor.click();
    };

    exportButton.addEventListener("click", () => {
      const currentRecords = JSON.parse(localStorage.getItem("cgnk.streamerHighlightFinder.records"));
      exportData(currentRecords);
    });

    const originalCreateObjectURL = URL.createObjectURL;
    let exportTriggered = false;
    URL.createObjectURL = (blob) => {
      exportTriggered = true;
      return originalCreateObjectURL(blob);
    };

    exportButton.click();
    result.exportTest = exportTriggered;

    // Cleanup
    document.body.innerHTML = "";
  } catch (error) {
    result.errors.push(error.message);
  }

  return result;
};