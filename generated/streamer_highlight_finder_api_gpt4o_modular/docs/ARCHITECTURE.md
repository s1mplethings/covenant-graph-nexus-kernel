# Architecture Documentation

## Overview
This document outlines the architecture for a game highlight detection application designed for streamers, content editors, and live stream operators. The application processes live event data, scores and ranks highlights, filters and sorts results, allows manual marking, and exports the final dataset. It is modular, browser-based, and uses local storage for data persistence.

---

## Modules

### Entry Point
- **Path**: `src/index.html`
- **Responsibility**: Provides the main structure of the application and links to scripts and styles.
- **Imports**: None
- **Exports**: None

### Styling
- **Path**: `src/styles.css`
- **Responsibility**: Defines the visual styling for the application.
- **Imports**: None
- **Exports**: None

### Application Logic
- **Path**: `src/app.js`
- **Responsibility**: Manages initialization, event listeners, and routing between screens.
- **Imports**:
  - `./utils/data_processor.js`
  - `./utils/local_storage_manager.js`
  - `./components/data_import.js`
  - `./components/highlight_detection.js`
  - `./components/filter_and_sort.js`
  - `./components/manual_marker.js`
  - `./components/export.js`
- **Exports**: None

### Data Processor
- **Path**: `src/utils/data_processor.js`
- **Responsibility**: Processes imported data, calculates scores, filters, and sorts the dataset.
- **Exports**:
  - `processData`
  - `calculateScores`
  - `filterData`
  - `sortData`
- **Imports**: None

### Local Storage Manager
- **Path**: `src/utils/local_storage_manager.js`
- **Responsibility**: Handles saving and loading data to/from localStorage.
- **Exports**:
  - `saveToLocalStorage`
  - `loadFromLocalStorage`
- **Imports**: None

### Data Import Component
- **Path**: `src/components/data_import.js`
- **Responsibility**: Manages data import functionality using FileReader and textarea input.
- **Exports**:
  - `renderDataImportScreen`
- **Imports**: None

### Highlight Detection Component
- **Path**: `src/components/highlight_detection.js`
- **Responsibility**: Implements highlight detection logic and displays results.
- **Exports**:
  - `renderHighlightDetectionScreen`
- **Imports**: None

### Filter and Sort Component
- **Path**: `src/components/filter_and_sort.js`
- **Responsibility**: Provides filter and sort controls and logic for the dataset.
- **Exports**:
  - `renderFilterAndSortScreen`
- **Imports**: None

### Manual Marker Component
- **Path**: `src/components/manual_marker.js`
- **Responsibility**: Allows users to manually add or edit highlights in the dataset.
- **Exports**:
  - `renderManualMarkerScreen`
- **Imports**: None

### Export Component
- **Path**: `src/components/export.js`
- **Responsibility**: Handles exporting the filtered dataset as a downloadable file.
- **Exports**:
  - `renderExportScreen`
- **Imports**: None

---

## Data Flow

### Input
1. **Data Import**: Users import JSON data via FileReader or textarea input.
2. **Processing**: Imported data is normalized and scored using `data_processor.js`.

### Processing
1. **Highlight Detection**: Scores are calculated based on predefined criteria (e.g., intensity, chat rate).
2. **Filtering and Sorting**: Users apply filters and sorting logic to refine the dataset.

### Output
1. **Manual Marking**: Users manually add or edit highlights.
2. **Export**: Filtered results are exported as a downloadable JSON file.

---

## API/Provider Role

### External API Gateway
- **Role**: Facilitates integration with external APIs for future enhancements (e.g., cloud storage, advanced analytics).
- **Scope**: Currently unused but reserved for future upgrades.

### Local Ollama Role
- **Role**: Acts as the local runtime executor, managing data persistence and routing logic.
- **Scope**: Handles local storage operations and ensures seamless user experience.

---

## Test Strategy

### Test Cases

#### 1. Data Import Functionality
- **Description**: Verify that JSON data can be imported via FileReader or textarea and is processed correctly.
- **Expected Result**: Imported data is displayed and processed into the application.

#### 2. Highlight Detection Scoring
- **Description**: Ensure that the scoring function calculates scores accurately and sorts items in descending order.
- **Expected Result**: Items are displayed in descending order of their scores.

#### 3. Filter and Sort Controls
- **Description**: Test that filter and sort controls work as expected for all fields.
- **Expected Result**: Dataset is filtered and sorted correctly based on user input.

#### 4. Manual Marker Functionality
- **Description**: Verify that users can manually add or edit highlights and see the updated dataset.
- **Expected Result**: New or edited highlights are appended to the dataset and displayed.

#### 5. Export Functionality
- **Description**: Test that the filtered dataset can be exported as a downloadable file.
- **Expected Result**: Filtered dataset is downloaded as a JSON file.

#### 6. LocalStorage Persistence
- **Description**: Ensure that working data is saved to localStorage and reloaded on page load.
- **Expected Result**: Data persists across page reloads.

---

## Acceptance Criteria

1. Application runs locally from `index.html` under `python -m http.server`.
2. JSON data is imported and processed using FileReader or textarea.
3. Scoring function assigns numeric scores and sorts items in descending order.
4. Filter controls are visible and functional for all fields.
5. Manual marker form appends new items to the dataset and rerenders results.
6. Export action uses Blob, URL.createObjectURL, and anchor download for filtered results.
7. Working data persists locally with localStorage and reloads on page load.

---

## Routing Policy

### Local Model Scope
- **Modules**: `local_librarian`, `route_manager`
- **Responsibility**: Handles local data persistence and screen routing.

### Provider Scope
- **Modules**: `project_generation`, `project_repair`, `final_project_logic`
- **Responsibility**: Manages project generation and repair logic.

---

## File Structure

### Expected Paths
- `project_architecture.json`
- `index.html`
- `styles.css`
- `src/core/scoring.js`
- `src/core/filtering.js`
- `src/core/importer.js`
- `src/core/exporter.js`
- `src/state/store.js`
- `src/ui/render.js`
- `src/ui/forms.js`
- `src/app.js`
- `data/sample_events.json`
- `tests/browser_smoke_test.js`
- `docs/ARCHITECTURE.md`
- `README.md`
- `TEST_PLAN.md`

---

## Conclusion
This architecture ensures modularity, scalability, and ease of use for the target audience. The application is designed to meet all acceptance criteria and provide a seamless experience for detecting and managing game highlights.