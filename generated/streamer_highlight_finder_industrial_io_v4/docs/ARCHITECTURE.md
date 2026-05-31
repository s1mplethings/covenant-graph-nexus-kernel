# Architecture Documentation: Game Stream Highlight Analyzer

## Overview

The **Game Stream Highlight Analyzer** is a modular, browser-based application designed to identify, score, and export high-impact moments from game streams. It leverages multi-source data (e.g., platform event logs, chat analytics, video metadata, manual annotations) to provide a streamlined workflow for streamers, editors, and platform operators. The application is implemented as a static web app, running locally via `index.html`, with modular JavaScript (ES modules) under `src/`, and sample data in JSON format under `data/`.

---

## Architecture Components

### 1. **Data Ingestion Module**
   - **Responsibility**: Handles importing industrial input bundles containing platform logs, chat data, video metadata, manual annotations, and operational reviews.
   - **Implementation**: 
     - Located in `src/core/importer.js`.
     - Functions: `parseRecordsFromText`, `normalizeRecord`, `importData`.
     - Reads JSON data from file input or textarea, normalizes it into a consistent format, and prepares it for processing.
   - **Data Flow**: 
     - Input: `data/industrial_input_bundle.json`.
     - Output: Normalized `processed_data` passed to the Highlight Scoring Engine.

---

### 2. **Highlight Scoring Engine**
   - **Responsibility**: Scores and ranks moments based on multi-source data using predefined criteria.
   - **Implementation**: 
     - Located in `src/core/scoring.js`.
     - Functions: `scoreRecord`, `sortRecords`.
     - Assigns a numeric score to each record based on fields like `intensity`, `chatRate`, and `viewerSpike`.
   - **Data Flow**: 
     - Input: `processed_data` from the Data Ingestion Module.
     - Output: `scored_highlights` sorted in descending order of score.

---

### 3. **Filtering and Sorting Module**
   - **Responsibility**: Enables users to filter and sort highlights by game, streamer, category, and score.
   - **Implementation**: 
     - Located in `src/core/filtering.js`.
     - Functions: `applyFilters`.
     - Applies user-defined filters to the scored highlights.
   - **Data Flow**: 
     - Input: `scored_highlights` from the Highlight Scoring Engine.
     - Output: `filtered_highlights` displayed in the GUI.

---

### 4. **Manual Annotation Tool**
   - **Responsibility**: Allows users to add or adjust highlight tags and append new items to the dataset.
   - **Implementation**: 
     - Located in `src/core/manual_annotation.js`.
     - Functions: `readManualMarker`, `appendRecord`.
     - Adds user-defined records to the working dataset and triggers a re-render.
   - **Data Flow**: 
     - Input: `filtered_highlights` from the Filtering and Sorting Module.
     - Output: `updated_highlights` with user annotations.

---

### 5. **Export Module**
   - **Responsibility**: Generates downloadable highlight lists and clips based on user-selected criteria.
   - **Implementation**: 
     - Located in `src/core/exporter.js`.
     - Functions: `downloadJson`, `exportData`.
     - Uses `Blob` and `URL.createObjectURL` to create downloadable files.
   - **Data Flow**: 
     - Input: `updated_highlights` from the Manual Annotation Tool.
     - Output: `exported_highlights` as JSON files.

---

### 6. **Local Storage Handler**
   - **Responsibility**: Persists working data locally and reloads it on page load.
   - **Implementation**: 
     - Located in `src/state/store.js`.
     - Functions: `loadFromLocalStorage`, `saveToLocalStorage`.
     - Uses `localStorage` to save and retrieve the current dataset.
   - **Data Flow**: 
     - Input: `updated_highlights`.
     - Output: `persisted_data` reloaded on page refresh.

---

### 7. **GUI Interface**
   - **Responsibility**: Provides a user-friendly interface for importing data, visualizing highlights, filtering, annotating, and exporting results.
   - **Implementation**: 
     - Located in `src/ui/render.js` and `src/ui/forms.js`.
     - Functions: `renderRecords`, `setupForms`, `bindDom`.
     - Displays highlights in a card-based layout and binds user actions to the underlying modules.
   - **Data Flow**: 
     - Input: `all_modules`.
     - Output: `user_actions` triggering module interactions.

---

## Data Flow

1. **Input**: Industrial input bundles (`data/industrial_input_bundle.json`) are imported via the Data Ingestion Module.
2. **Processing**: Data is normalized and passed to the Highlight Scoring Engine, which assigns scores and ranks moments.
3. **Filtering**: Users apply filters via the Filtering and Sorting Module to refine the results.
4. **Annotation**: Users add manual tags or adjust highlights using the Manual Annotation Tool.
5. **Export**: Filtered and annotated highlights are exported as JSON files via the Export Module.
6. **Persistence**: Working data is saved to `localStorage` and reloaded on page refresh.

---

## API/Provider Role

- **Local Ollama Role**: The application operates entirely in the browser, leveraging local resources such as `localStorage` and `FileReader`. No external API calls are made in the current implementation.
- **Provider Role**: Future iterations may integrate with external APIs for live data retrieval or advanced processing.

---

## Self-Test and Quality Evaluation

### Browser Smoke Tests
- **Location**: `tests/browser_smoke_test.js`.
- **Purpose**: Verify that the app runs locally, processes data, and renders results correctly.
- **Key Checks**:
  - Importing JSON data.
  - Scoring and sorting records.
  - Applying filters and rendering results.
  - Adding manual annotations.
  - Exporting filtered results.

### Industrial I/O Smoke Tests
- **Location**: `tests/industrial_io_smoke_test.js`.
- **Purpose**: Simulate industrial-grade input bundles and validate output against `data/expected_outputs.json`.
- **Key Checks**:
  - Input normalization.
  - Scoring accuracy.
  - Filter logic correctness.
  - Exported data integrity.

---

## Future Paths

### Potential Enhancements
1. **Backend Integration**:
   - Add server-side processing for large datasets.
   - Enable live data retrieval from streaming platforms.
2. **Advanced Analytics**:
   - Incorporate machine learning models for more accurate scoring.
   - Analyze trends across multiple streams and games.
3. **Collaboration Features**:
   - Allow multiple users to collaborate on highlight selection.
   - Provide version control for annotations and exports.

---

## File Structure

```
project/
├── index.html
├── styles.css
├── src/
│   ├── core/
│   │   ├── importer.js
│   │   ├── scoring.js
│   │   ├── filtering.js
│   │   ├── manual_annotation.js
│   │   ├── exporter.js
│   │   └── store.js
│   ├── ui/
│   │   ├── render.js
│   │   ├── forms.js
│   └── app.js
├── data/
│   ├── sample_events.json
│   ├── industrial_input_bundle.json
│   └── expected_outputs.json
├── tests/
│   ├── browser_smoke_test.js
│   └── industrial_io_smoke_test.js
├── docs/
│   ├── ARCHITECTURE.md
│   ├── INPUT_OUTPUT_SPEC.md
│   ├── USER_ANALYSIS.md
│   ├── MARKET_RESEARCH.md
│   ├── TECHNICAL_PATH.md
│   └── UX_DESIGN_SPEC.md
└── README.md
```

---

## Conclusion

The **Game Stream Highlight Analyzer** is a robust, modular tool designed to meet the needs of streamers, editors, and platform operators. Its local, browser-based implementation ensures accessibility and ease of use, while its modular architecture allows for future scalability and integration with advanced technologies.