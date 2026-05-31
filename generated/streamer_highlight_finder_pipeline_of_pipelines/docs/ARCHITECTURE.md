# Architecture Documentation: Highlight Moment Detector

## Overview
The **Highlight Moment Detector** is a modular web application designed to identify, score, and manage highlight moments from live stream event data. It provides tools for importing data, processing and scoring events, filtering results, manually marking highlights, and exporting the final dataset. The application is built with a focus on local storage and browser-based execution, ensuring ease of use for streamers, content editors, and live stream operators.

---

## Modules

### 1. **Data Import Module**
- **Path**: `src/data_import.js`
- **Responsibility**: Handles importing live stream event data via FileReader or textarea input.
- **Exports**:
  - `importData`: Parses and normalizes JSON data from user input.
- **Imports**: None.

---

### 2. **Data Processing Module**
- **Path**: `src/data_processing.js`
- **Responsibility**: Processes imported data, calculates scores, and sorts items by score.
- **Exports**:
  - `processData`: Processes raw data into a usable format.
  - `calculateScore`: Assigns a numeric score to each record based on intensity, chat rate, and other factors.
  - `sortByScore`: Sorts records in descending order of score.
- **Imports**:
  - `src/data_import.js`

---

### 3. **Filter Controls Module**
- **Path**: `src/filter_controls.js`
- **Responsibility**: Provides filter controls for streamer, game, category, and score.
- **Exports**:
  - `applyFilters`: Filters the dataset based on user input.
  - `renderFilters`: Renders filter UI components.
- **Imports**:
  - `src/data_processing.js`

---

### 4. **Manual Marker Module**
- **Path**: `src/manual_marker.js`
- **Responsibility**: Allows users to manually mark highlights and append them to the dataset.
- **Exports**:
  - `addManualHighlight`: Adds a manually marked highlight to the dataset.
- **Imports**:
  - `src/data_processing.js`

---

### 5. **Export Data Module**
- **Path**: `src/export_data.js`
- **Responsibility**: Exports filtered results as a downloadable file using Blob and URL.createObjectURL.
- **Exports**:
  - `exportHighlights`: Exports the current filtered dataset.
- **Imports**:
  - `src/filter_controls.js`

---

### 6. **Local Storage Module**
- **Path**: `src/local_storage.js`
- **Responsibility**: Persists working data locally using localStorage and reloads it on page load.
- **Exports**:
  - `saveToLocalStorage`: Saves the current dataset to localStorage.
  - `loadFromLocalStorage`: Loads the dataset from localStorage.
- **Imports**:
  - `src/data_processing.js`

---

### 7. **UI Renderer Module**
- **Path**: `src/ui_renderer.js`
- **Responsibility**: Renders UI components such as tables, filters, and forms.
- **Exports**:
  - `renderTable`: Renders the dataset as a table.
  - `renderForm`: Renders forms for filters and manual markers.
  - `renderDashboard`: Renders the main dashboard UI.
- **Imports**:
  - `src/filter_controls.js`
  - `src/manual_marker.js`
  - `src/export_data.js`

---

## Data Flow

1. **Import Data**:
   - Users upload JSON data via file input or textarea.
   - `importData` parses and normalizes the data.

2. **Process Data**:
   - `processData` calculates scores for each record using `calculateScore`.
   - Records are sorted in descending order using `sortByScore`.

3. **Filter Data**:
   - Users apply filters via the UI.
   - `applyFilters` narrows down the dataset based on user input.

4. **Manual Highlighting**:
   - Users manually mark highlights using the manual marker form.
   - `addManualHighlight` appends the new record to the dataset.

5. **Export Data**:
   - Users export the filtered dataset as a JSON file.
   - `exportHighlights` generates a downloadable file.

6. **Local Storage**:
   - The dataset is saved to localStorage using `saveToLocalStorage`.
   - On page reload, `loadFromLocalStorage` restores the dataset.

7. **UI Rendering**:
   - The UI is dynamically updated using `renderTable`, `renderForm`, and `renderDashboard`.

---

## API/Provider Role

### Local Ollama Role
- **Scope**: Handles local data processing, storage, and UI rendering.
- **Responsibilities**:
  - Parsing and normalizing imported data.
  - Calculating scores and sorting records.
  - Managing local storage for persistence.
  - Rendering UI components and handling user interactions.

### External API/Provider Role
- **Scope**: Not applicable in this version. The application is self-contained and does not rely on external APIs.

---

## Test Strategy

### Test Cases

1. **Import JSON Data**
   - **Expected Result**: Data is successfully parsed and displayed in the UI.

2. **Score Calculation**
   - **Expected Result**: Scores are calculated correctly based on intensity, chat rate, and other factors.

3. **Filter Application**
   - **Expected Result**: Filters correctly narrow down the dataset based on user input.

4. **Manual Highlight Addition**
   - **Expected Result**: Manually added highlights appear in the dataset and are saved locally.

5. **Export Functionality**
   - **Expected Result**: Filtered results are exported as a downloadable file.

6. **Local Storage Persistence**
   - **Expected Result**: Data persists across page reloads using localStorage.

---

## Acceptance Criteria

1. The project must run locally from `index.html` using `python -m http.server`.
2. JSON data must be imported via FileReader or textarea and processed by the app.
3. Scores must be calculated and records sorted in descending order.
4. Filter controls must be visible and functional.
5. A manual marker form must allow users to append new records.
6. Filtered results must be exportable as a JSON file.
7. Data must persist across page reloads using localStorage.

---

## Conclusion

The **Highlight Moment Detector** is a modular, browser-based application designed to streamline the process of identifying and managing highlight moments from live stream data. Its architecture ensures scalability, maintainability, and ease of use for its target audience.