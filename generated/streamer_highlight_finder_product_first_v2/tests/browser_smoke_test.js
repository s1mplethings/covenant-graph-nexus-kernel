window.runSmokeTest = async function () {
  const localStorageKey = 'cgnk.streamerHighlightFinder.records';
  const result = {
    importTest: false,
    renderTest: false,
    filterTest: false,
    sortTest: false,
    manualMarkerTest: false,
    exportTest: false,
    localStorageTest: false,
    errors: []
  };

  try {
    // Step 1: Import sample data through textarea
    const sampleData = [
      {
        streamer: "Streamer1",
        game: "Game1",
        timestamp: "2023-10-01T12:00:00Z",
        time: "00:10:00",
        category: "Category1",
        intensity: 5,
        chatRate: 10,
        keywords: ["exciting", "clutch"],
        title: "Epic Moment",
        description: "An epic moment in the game.",
        score: 95
      },
      {
        streamer: "Streamer2",
        game: "Game2",
        timestamp: "2023-10-01T13:00:00Z",
        time: "00:20:00",
        category: "Category2",
        intensity: 3,
        chatRate: 5,
        keywords: ["funny", "unexpected"],
        title: "Funny Fail",
        description: "A hilarious fail moment.",
        score: 80
      }
    ];

    const textarea = document.getElementById('json-textarea');
    const importButton = document.getElementById('import-button');
    textarea.value = JSON.stringify(sampleData);
    importButton.click();

    // Wait for data to be processed and rendered
    await new Promise(resolve => setTimeout(resolve, 1000));

    // Step 2: Verify rendering of imported data
    const recordsContainer = document.getElementById('records-container');
    const renderedRecords = recordsContainer.querySelectorAll('.highlight-card');
    if (renderedRecords.length === sampleData.length) {
      const allFieldsVisible = Array.from(renderedRecords).every(card => {
        const title = card.querySelector('.highlight-title');
        const streamer = card.querySelector('.metadata-row.streamer');
        const game = card.querySelector('.metadata-row.game');
        const category = card.querySelector('.metadata-row.category');
        const score = card.querySelector('.score-badge');
        const description = card.querySelector('.metadata-row.description');
        return title && streamer && game && category && score && description;
      });
      if (allFieldsVisible) {
        result.renderTest = true;
      } else {
        result.errors.push('Not all required fields are visible in rendered records.');
      }
    } else {
      result.errors.push('Mismatch in number of rendered records.');
    }

    // Step 3: Verify filtering functionality
    const filterForm = document.getElementById('filter-form');
    const filterStreamer = document.getElementById('filterStreamer');
    filterStreamer.value = "Streamer1";
    filterForm.dispatchEvent(new Event('submit'));

    await new Promise(resolve => setTimeout(resolve, 500));
    const filteredRecords = recordsContainer.querySelectorAll('.highlight-card');
    if (filteredRecords.length === 1 && filteredRecords[0].querySelector('.highlight-title').textContent === "Epic Moment") {
      result.filterTest = true;
    } else {
      result.errors.push('Filtering by streamer failed.');
    }

    // Step 4: Verify sorting functionality
    const sortButton = document.querySelector('[data-sort="score-desc"]');
    sortButton.click();

    await new Promise(resolve => setTimeout(resolve, 500));
    const sortedRecords = recordsContainer.querySelectorAll('.highlight-card');
    const scores = Array.from(sortedRecords).map(card => parseInt(card.querySelector('.score-badge').textContent, 10));
    if (scores.join(',') === "95,80") {
      result.sortTest = true;
    } else {
      result.errors.push('Sorting by score failed.');
    }

    // Step 5: Verify manual marker functionality
    const manualForm = document.getElementById('manual-form');
    const manualTitle = manualForm.querySelector('[name="title"]');
    const manualStreamer = manualForm.querySelector('[name="streamer"]');
    const manualGame = manualForm.querySelector('[name="game"]');
    const manualCategory = manualForm.querySelector('[name="category"]');
    const manualScore = manualForm.querySelector('[name="score"]');
    const manualDescription = manualForm.querySelector('[name="description"]');

    manualTitle.value = "Manual Highlight";
    manualStreamer.value = "Streamer3";
    manualGame.value = "Game3";
    manualCategory.value = "Category3";
    manualScore.value = 70;
    manualDescription.value = "A manually added highlight.";
    manualForm.dispatchEvent(new Event('submit'));

    await new Promise(resolve => setTimeout(resolve, 500));
    const manualRecord = Array.from(recordsContainer.querySelectorAll('.highlight-card')).find(card => {
      return card.querySelector('.highlight-title').textContent === "Manual Highlight";
    });
    if (manualRecord) {
      result.manualMarkerTest = true;
    } else {
      result.errors.push('Manual marker functionality failed.');
    }

    // Step 6: Verify export functionality
    const exportButton = document.getElementById('export-button');
    const originalCreateObjectURL = URL.createObjectURL;
    let exportTriggered = false;
    URL.createObjectURL = function (blob) {
      exportTriggered = true;
      return originalCreateObjectURL(blob);
    };
    exportButton.click();

    await new Promise(resolve => setTimeout(resolve, 500));
    if (exportTriggered) {
      result.exportTest = true;
    } else {
      result.errors.push('Export functionality failed.');
    }
    URL.createObjectURL = originalCreateObjectURL;

    // Step 7: Verify localStorage persistence
    const storedData = JSON.parse(localStorage.getItem(localStorageKey));
    if (storedData && storedData.length === sampleData.length + 1) {
      result.localStorageTest = true;
    } else {
      result.errors.push('LocalStorage persistence failed.');
    }

  } catch (error) {
    result.errors.push(`Unexpected error: ${error.message}`);
  }

  return result;
};