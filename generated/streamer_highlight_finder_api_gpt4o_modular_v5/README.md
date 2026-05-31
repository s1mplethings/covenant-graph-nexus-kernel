# Game Stream Highlight Detector

This project is a modular web application designed to detect and manage highlights from game streaming events. It allows users to import event data, automatically score and sort highlights, filter results, manually mark highlights, export data, and run tests. The application is built with JavaScript and runs locally in a browser.

## Table of Contents
- [Getting Started](#getting-started)
- [Features](#features)
  - [Import](#import)
  - [Scoring](#scoring)
  - [Filtering](#filtering)
  - [Manual Markers](#manual-markers)
  - [Export](#export)
  - [Sample Data](#sample-data)
  - [Smoke Tests](#smoke-tests)
- [Project Structure](#project-structure)
- [Running the Application](#running-the-application)
- [Testing](#testing)

---

## Getting Started

To run this project locally, follow these steps:

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

---

## Features

### Import
- **How to Use**: 
  - Use the file input or paste JSON data into the textarea on the "Import Data" screen.
  - Click the "Import" button to load the data into the application.
- **Supported Formats**: JSON files or raw JSON text.
- **Data Contract**: Each record must include fields like `streamer`, `game`, `timestamp`, `category`, `intensity`, `chatRate`, `keywords`, `title`, `description`, and `score`.

### Scoring
- **How It Works**:
  - The application automatically assigns a score to each record based on predefined logic (e.g., intensity, chat rate, and keywords).
  - Highlights are sorted in descending order of their scores.
- **Customization**: Scoring logic can be modified in `src/core/scoring.js`.

### Filtering
- **How to Use**:
  - Use the filter form to narrow down results by `streamer`, `game`, `category`, or minimum `score`.
  - Click "Apply Filters" to update the displayed highlights.
- **Implementation**: Filtering logic is handled in `src/core/filtering.js`.

### Manual Markers
- **How to Use**:
  - Use the manual marker form to add a new highlight.
  - Provide details such as `streamer`, `game`, `timestamp`, `category`, and `description`.
  - Click "Add Highlight" to append the new record to the dataset.
- **Persistence**: Manually added highlights are saved locally and persist across sessions.

### Export
- **How to Use**:
  - Click the "Export" button to download the current filtered highlights as a JSON file.
- **Implementation**: Export functionality uses `Blob` and `URL.createObjectURL` in `src/core/exporter.js`.

### Sample Data
- **Location**: `data/sample_events.json`
- **How to Use**:
  - Import the sample data to explore the application's features.
  - The sample data includes realistic records for testing and demonstration.

### Smoke Tests
- **How to Run**:
  - Open the browser console and execute the smoke test script located in `tests/browser_smoke_test.js`.
- **Purpose**: Verifies that the core functionalities (import, scoring, filtering, manual markers, export) work as expected.

---

## Project Structure

```
├── index.html               # Main entry point
├── styles.css               # Application styles
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
│   ├── app.js               # Main application logic
├── data/
│   ├── sample_events.json   # Sample data for testing
├── tests/
│   ├── browser_smoke_test.js # Smoke test script
├── docs/
│   ├── ARCHITECTURE.md      # Detailed architecture documentation
│   ├── TEST_PLAN.md         # Test plan and strategy
├── README.md                # Project documentation (this file)
```

---

## Running the Application

1. Ensure you have Python installed on your system.
2. Start a local HTTP server:
   ```bash
   python -m http.server
   ```
3. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```
4. Use the application to import data, detect highlights, filter results, add manual markers, and export data.

---

## Testing

### Unit Tests
- Each module has unit tests to verify its functionality.
- Example: Scoring logic is tested in isolation to ensure correct score calculation.

### Integration Tests
- Verifies that modules work together as expected.
- Example: Ensures that imported data is correctly scored and displayed.

### Smoke Tests
- Run the smoke test script in `tests/browser_smoke_test.js` to validate core functionalities.

### Performance Tests
- Tests the application's performance with large datasets to ensure smooth operation.

### Acceptance Tests
- Confirms that all acceptance criteria are met, including import, scoring, filtering, manual markers, export, and local storage persistence.