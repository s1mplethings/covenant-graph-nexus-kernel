# Game Stream Highlight Identifier

## Purpose
The **Game Stream Highlight Identifier** is a browser-based tool designed to help users identify, score, filter, and export high-impact moments from game streams. It processes structured industrial input bundles, allowing users to efficiently curate highlights for content creation, platform promotion, or operational review.

## Target Users
1. **Game Streamers**:
   - **Needs**: Efficiently identify high-impact moments, improve content quality, and save time on manual review.
   - **Pain Points**: Time-consuming manual review, difficulty identifying audience-resonating moments, and limited tools for organizing/exporting highlights.

2. **Content Managers/Streaming Platform Operators**:
   - **Needs**: Streamline content curation, automate highlight identification, and ensure compliance with platform guidelines.
   - **Pain Points**: High operational overhead, inconsistent highlight quality, and challenges in scaling content curation.

## Technical Path
This project is implemented as a **static browser application** with the following characteristics:
- **Input**: JSON data via file upload or textarea, including industrial input bundles.
- **Processing**: Scoring and sorting of highlights based on engagement metrics and metadata.
- **Storage**: LocalStorage for persistence.
- **Output**: Exportable JSON files using Blob and URL.createObjectURL.
- **Dependencies**: No external libraries, frameworks, or backend services (e.g., no React, Node.js, or databases).

## How to Run Locally
1. Clone or download the project repository.
2. Navigate to the project directory in your terminal.
3. Run the following command to start a local server:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000` to access the application.

## How to Use

### Importing Data
1. **Textarea Import**:
   - Paste JSON data into the provided textarea on the interface.
   - Click the "Import" button to process the data.
2. **File Import**:
   - Use the file input to upload a JSON file containing structured data.
   - The app will parse and display the imported records.

### Scoring and Sorting
- The app automatically assigns scores to imported records based on predefined criteria (e.g., engagement metrics, chat activity).
- Records are sorted in descending order of their scores for easy review.

### Filtering
- Use the filter form to narrow down results based on:
  - **Streamer**: Filter by specific streamers.
  - **Game**: Filter by game titles.
  - **Category**: Filter by content categories.
  - **Minimum Score**: Set a threshold to display only high-scoring highlights.

### Manual Markers
- Add new highlights manually using the "Manual Marker" form:
  - Fill in the required fields (e.g., title, description, score).
  - Submit the form to append the new record to the dataset and update the display.

### Exporting Data
- Export the current filtered dataset as a JSON file:
  - Click the "Export" button to download the file.
  - The exported file will include all visible records in the current view.

### Sample Data
- The project includes sample data files for testing:
  - `data/sample_events.json`: Example input data.
  - `data/industrial_input_bundle.json`: Simulated industrial input bundle.
  - `data/expected_outputs.json`: Expected output format for validation.

### Industrial Input Bundle
- The industrial input bundle (`data/industrial_input_bundle.json`) simulates real-world data sources such as:
  - Platform event logs.
  - Chat analytics.
  - Manual annotations.
  - Public clip metadata.
  - Operational audits.

### Expected Outputs
- Processed highlights are scored, sorted, and filtered based on user-defined criteria.
- Exported JSON files contain the curated list of highlights, ready for further editing or platform upload.

### Smoke Tests
1. **Browser Smoke Test**:
   - Validates the app's functionality in a browser environment.
   - Ensures proper rendering, data import/export, and interaction handling.
2. **Industrial I/O Smoke Test**:
   - Tests the app's ability to process industrial input bundles and generate expected outputs.

## Project Structure
- **HTML**: `index.html` - Main entry point for the application.
- **CSS**: `styles.css` - Styling for the user interface.
- **JavaScript**:
  - `src/core/`: Core logic for scoring, filtering, importing, and exporting.
  - `src/state/`: LocalStorage management for data persistence.
  - `src/ui/`: Rendering and form handling for the user interface.
  - `src/app.js`: Main application logic.
- **Data**:
  - `data/sample_events.json`: Sample input data.
  - `data/industrial_input_bundle.json`: Simulated industrial input bundle.
  - `data/expected_outputs.json`: Expected output format.
- **Tests**:
  - `tests/browser_smoke_test.js`: Browser functionality test.
  - `tests/industrial_io_smoke_test.js`: Industrial input/output test.

## Limitations
This project does not include:
- Drag-and-drop functionality.
- Timeline visualization.
- Collaboration or sharing features.
- Machine learning, NLP, or computer vision capabilities.
- Backend services or database integration.

## Conclusion
The **Game Stream Highlight Identifier** provides a modular, efficient, and user-friendly solution for identifying and exporting game stream highlights. It is tailored to the needs of streamers and content managers, ensuring scalability and usability without requiring external dependencies.