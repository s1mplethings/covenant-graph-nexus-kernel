# Highlight Moment Detector

The **Highlight Moment Detector** is a modular web application designed to help game streamers, content editors, and live stream operators identify and manage highlight moments from live stream event data. This README provides instructions on how to run the project locally, use its features, and test its functionality.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Features](#features)
   - [Import Data](#import-data)
   - [Scoring and Sorting](#scoring-and-sorting)
   - [Filtering](#filtering)
   - [Manual Markers](#manual-markers)
   - [Export Data](#export-data)
3. [Sample Data](#sample-data)
4. [Running Smoke Tests](#running-smoke-tests)
5. [Project Structure](#project-structure)

---

## Getting Started

### Prerequisites

- A modern web browser (e.g., Chrome, Firefox, Edge).
- Python 3 installed on your system (for running a local server).

### Steps to Run Locally

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/highlight_moment_detector.git
   cd highlight_moment_detector
   ```

2. Start a local server:
   ```bash
   python -m http.server
   ```

3. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

4. The application will load, and you can begin using it.

---

## Features

### Import Data

- **How to Use**:
  1. Click the "Choose File" button or paste JSON data into the provided textarea.
  2. Click the "Import" button to load the data.
- **Supported Format**:
  The imported JSON should match the following structure:
  ```json
  [
    {
      "streamer": "string",
      "game": "string",
      "timestamp": "string",
      "time": "string",
      "category": "string",
      "intensity": "number",
      "chatRate": "number",
      "keywords": ["string"],
      "title": "string",
      "description": "string",
      "score": "number"
    }
  ]
  ```

### Scoring and Sorting

- **Automatic Scoring**:
  Each record is scored based on factors like `intensity`, `chatRate`, and `keywords`.
- **Sorting**:
  Records are automatically sorted in descending order of their scores.

### Filtering

- **Filter Options**:
  - Streamer
  - Game
  - Category
  - Minimum Score
- **How to Use**:
  1. Use the filter form to specify your criteria.
  2. Click "Apply Filters" to narrow down the results.

### Manual Markers

- **Add Highlights**:
  1. Fill out the manual marker form with details of the highlight.
  2. Click "Add Highlight" to append it to the dataset.
- **Persistence**:
  Manually added highlights are saved locally and persist across page reloads.

### Export Data

- **Export Highlights**:
  1. Click the "Export" button to download the current filtered dataset as a JSON file.
  2. The file will be named `highlights.json`.

---

## Sample Data

Sample data is provided in the `data/sample_events.json` file. You can use this file to test the application by importing it.

---

## Running Smoke Tests

Smoke tests are included to verify the core functionality of the application.

### Steps to Run Tests

1. Open the `tests/browser_smoke_test.js` file in your preferred editor.
2. Follow the instructions in the file to execute the tests in your browser console.

### Test Cases

- **Import JSON Data**: Verify that data is successfully parsed and displayed.
- **Score Calculation**: Ensure scores are calculated correctly.
- **Filter Application**: Confirm filters work as expected.
- **Manual Highlight Addition**: Check that manually added highlights are saved and displayed.
- **Export Functionality**: Validate that filtered results are exported correctly.
- **Local Storage Persistence**: Ensure data persists across page reloads.

---

## Project Structure

```
highlight_moment_detector/
├── index.html               # Main HTML file
├── styles.css               # Stylesheet
├── src/
│   ├── core/
│   │   ├── scoring.js       # Scoring logic
│   │   ├── filtering.js     # Filtering logic
│   │   ├── importer.js      # Data import logic
│   │   ├── exporter.js      # Data export logic
│   ├── state/
│   │   ├── store.js         # Local storage management
│   ├── ui/
│   │   ├── render.js        # UI rendering logic
│   │   ├── forms.js         # Form handling logic
│   └── app.js               # Main application logic
├── data/
│   ├── sample_events.json   # Sample data for testing
├── tests/
│   ├── browser_smoke_test.js # Smoke tests
├── docs/
│   ├── ARCHITECTURE.md      # Architecture documentation
│   ├── TEST_PLAN.md         # Test plan
├── README.md                # This file
```

---

Enjoy using the **Highlight Moment Detector**! If you encounter any issues, feel free to open an issue on the repository.