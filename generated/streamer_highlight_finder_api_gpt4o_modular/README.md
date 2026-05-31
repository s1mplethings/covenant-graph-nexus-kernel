# Game Highlight Detection Project

This project is designed to help game streamers, content editors, and live stream operators identify and manage highlight moments from streaming data. It provides functionality for importing data, scoring and sorting highlights, filtering results, manually marking highlights, exporting data, and running smoke tests.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Running the Project Locally](#running-the-project-locally)
- [Features](#features)
  - [Import](#import)
  - [Scoring](#scoring)
  - [Filtering](#filtering)
  - [Manual Markers](#manual-markers)
  - [Export](#export)
  - [Sample Data](#sample-data)
  - [Smoke Tests](#smoke-tests)
- [Project Structure](#project-structure)

---

## Prerequisites

To run this project locally, you need:
- Python 3 installed on your system.
- A modern web browser (e.g., Chrome, Firefox, Edge).

---

## Running the Project Locally

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```

2. Start a local HTTP server:
   ```bash
   python -m http.server
   ```

3. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

4. The application will load the `index.html` file and initialize the project.

---

## Features

### Import
- **How to Use**:
  - Navigate to the "Data Import" screen.
  - Use the file input or paste JSON data into the textarea.
  - Click the "Import" button to load the data into the application.
- **Details**:
  - The imported data is processed and normalized using the `src/core/importer.js` module.
  - Supported fields include `streamer`, `game`, `timestamp`, `time`, `category`, `intensity`, `chatRate`, `keywords`, `title`, `description`, and `score`.

### Scoring
- **How to Use**:
  - After importing data, navigate to the "Highlight Detection" screen.
  - The application automatically calculates scores for each record based on intensity, chat rate, and other factors.
- **Details**:
  - Scoring logic is implemented in `src/core/scoring.js`.
  - Records are sorted in descending order of their scores.

### Filtering
- **How to Use**:
  - Navigate to the "Filter and Sort" screen.
  - Use the filter form to specify criteria such as streamer, game, category, or minimum score.
  - Click "Apply Filters" to update the displayed results.
- **Details**:
  - Filtering logic is implemented in `src/core/filtering.js`.

### Manual Markers
- **How to Use**:
  - Navigate to the "Manual Marker" screen.
  - Fill out the form to add a new highlight record.
  - Click "Add Highlight" to append the record to the dataset.
- **Details**:
  - Manual marker functionality is handled by `src/ui/forms.js` and updates the dataset dynamically.

### Export
- **How to Use**:
  - Navigate to the "Export" screen.
  - Click the "Export Data" button to download the filtered dataset as a JSON file.
- **Details**:
  - Export functionality is implemented in `src/core/exporter.js` using Blob and URL.createObjectURL.

### Sample Data
- **How to Use**:
  - Sample data is provided in `data/sample_events.json`.
  - You can import this file to test the application.
- **Details**:
  - The sample data includes realistic records with fields such as streamer, game, timestamp, and score.

### Smoke Tests
- **How to Use**:
  - Run the smoke test script using a browser testing tool or manually verify functionality.
- **Details**:
  - Smoke tests are defined in `tests/browser_smoke_test.js` and cover import, scoring, filtering, manual markers, and export.

---

## Project Structure

```
├── index.html                # Entry point for the application
├── styles.css                # Application styling
├── src/
│   ├── app.js                # Main application logic
│   ├── core/
│   │   ├── scoring.js        # Scoring logic
│   │   ├── filtering.js      # Filtering logic
│   │   ├── importer.js       # Data import logic
│   │   ├── exporter.js       # Data export logic
│   ├── state/
│   │   ├── store.js          # LocalStorage management
│   ├── ui/
│   │   ├── render.js         # UI rendering logic
│   │   ├── forms.js          # Form handling logic
├── data/
│   ├── sample_events.json    # Sample data for testing
├── tests/
│   ├── browser_smoke_test.js # Smoke test script
├── docs/
│   ├── ARCHITECTURE.md       # Detailed architecture documentation
│   ├── TEST_PLAN.md          # Test plan documentation
├── README.md                 # Project README
```

---

Enjoy using the Game Highlight Detection Project!