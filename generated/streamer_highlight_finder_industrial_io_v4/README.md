# Game Stream Highlight Analyzer

## Purpose
The **Game Stream Highlight Analyzer** is a modular, browser-based tool designed to help game streamers, content editors, and platform operators identify, score, filter, and export high-impact moments from game streams. By leveraging multi-source data such as platform event logs, chat analytics, video metadata, and manual annotations, the tool streamlines the process of creating engaging highlight reels.

## Target Users
1. **Game Streamers**  
   - **Needs**: Efficiently identify impactful moments, improve content quality, and save time on manual editing.  
   - **Pain Points**: Reviewing hours of footage manually and difficulty identifying audience-resonating moments.

2. **Content Editors**  
   - **Needs**: Streamline highlight creation, filter and score moments quickly, and collaborate with streamers.  
   - **Pain Points**: Limited automation tools and challenges in managing large datasets.

3. **Platform Operators**  
   - **Needs**: Promote high-quality content, provide tools for creators, and analyze trends in high-performing moments.  
   - **Pain Points**: Lack of insights into engaging content and difficulty scaling highlight discovery.

## Technical Path
The project is implemented as a **local static browser application** with no external dependencies. It uses:
- **HTML, CSS, and JavaScript** for the front-end.
- **Browser local storage** for data persistence.
- Modular JavaScript for core functionalities like scoring, filtering, importing, exporting, and manual annotations.

### Key Features
- **Import**: Drag-and-drop or text-based JSON import of industrial input bundles.
- **Scoring**: Automatic scoring and ranking of moments based on multi-source data.
- **Filtering**: Filter highlights by streamer, game, category, and score.
- **Manual Markers**: Add custom highlights manually.
- **Export**: Download filtered highlights as JSON files.
- **Sample Data**: Preloaded sample data for testing and demonstration.
- **Local Storage**: Persist working data locally and reload it on page load.

## How to Run the Project Locally
1. Clone or download the project files.
2. Navigate to the project directory in your terminal.
3. Run the following command to start a local server:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000`.
5. The application will load, and you can begin using the tool.

## How to Use the Tool

### 1. Import
- Use the **Import Panel** to load data:
  - Drag-and-drop a JSON file into the file input.
  - Or paste JSON data into the provided textarea.
- Click the **Import** button to process the data.

### 2. Scoring
- The tool automatically scores imported records based on predefined criteria such as intensity, chat rate, and keywords.
- Records are sorted by score in descending order.

### 3. Filtering
- Use the **Filter Panel** to narrow down results:
  - Filter by **Streamer**, **Game**, **Category**, or **Score Range**.
- Click **Apply Filters** to update the results.

### 4. Manual Markers
- Use the **Manual Marker Form** to add custom highlights:
  - Fill in fields like **Streamer**, **Game**, **Timestamp**, **Category**, and **Description**.
  - Click **Add Highlight** to append the new record to the dataset.

### 5. Export
- Use the **Export Button** to download the current filtered results as a JSON file.

### 6. Sample Data
- Preloaded sample data is available for testing:
  - Located in `data/sample_events.json`.
  - Simulates industrial input bundles with fields like streamer, game, timestamp, category, intensity, and score.

### 7. Industrial Input Bundle
- Import industrial-grade input bundles from `data/industrial_input_bundle.json`.
- These bundles simulate real-world data sources such as platform event logs, chat analytics, and manual annotations.

### 8. Expected Outputs
- The tool generates outputs that match the structure in `data/expected_outputs.json`.
- Outputs include ranked highlights, export cut lists, and quality checks.

### 9. Smoke Tests
- **Browser Smoke Test**: Located in `tests/browser_smoke_test.js`. Verifies the app's functionality in a browser environment.
- **Industrial I/O Smoke Test**: Located in `tests/industrial_io_smoke_test.js`. Validates the processing of industrial input bundles and expected outputs.

## Project Structure
- **HTML**: `index.html` - Main entry point for the application.
- **CSS**: `styles.css` - Styling for the user interface.
- **JavaScript Modules**:
  - `src/core/scoring.js`: Scoring and ranking logic.
  - `src/core/filtering.js`: Filtering logic.
  - `src/core/importer.js`: Data import and normalization.
  - `src/core/exporter.js`: Export functionality.
  - `src/state/store.js`: Local storage handling.
  - `src/ui/render.js`: Rendering of records and summaries.
  - `src/ui/forms.js`: Form handling and event binding.
  - `src/app.js`: Main application logic.
- **Data**:
  - `data/sample_events.json`: Sample data for testing.
  - `data/industrial_input_bundle.json`: Simulated industrial input bundle.
  - `data/expected_outputs.json`: Expected outputs for validation.
- **Tests**:
  - `tests/browser_smoke_test.js`: Browser functionality tests.
  - `tests/industrial_io_smoke_test.js`: Industrial input/output tests.
- **Documentation**:
  - `docs/ARCHITECTURE.md`: Detailed architecture overview.
  - `docs/INPUT_OUTPUT_SPEC.md`: Input/output specifications.
  - `README.md`: This file.

## Acceptance Criteria
- The project runs locally using `python -m http.server`.
- Real JSON import and processing functionality.
- Scoring and sorting logic implemented in JavaScript.
- Visible filter controls with executable filtering logic.
- Manual marker form for adding new highlights.
- Export functionality using Blob and URL.createObjectURL.
- Data persistence with localStorage.

## License
This project is licensed under the MIT License. See `LICENSE` for details.