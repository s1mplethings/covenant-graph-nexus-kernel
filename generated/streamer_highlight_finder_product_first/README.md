# Game Stream Highlight Tool

## Purpose
The **Game Stream Highlight Tool** is a modular web application designed to help streamers, content editors, and platform managers identify, edit, and export highlight moments from gaming streams. By leveraging AI/ML models and providing intuitive tools, the application streamlines the process of creating engaging highlight reels, saving time and improving content quality.

---

## Target Users
### 1. **Streamers**
   - **Description**: Content creators who stream games and want to identify their most engaging moments.
   - **Needs**:
     - Automated detection of high-engagement moments.
     - Filtering and sorting highlights by game, category, or score.
     - Manual adjustment tools for fine-tuning.
   - **Pain Points**:
     - Reviewing hours of footage is time-consuming.
     - Difficulty identifying audience-resonating moments.

### 2. **Content Editors**
   - **Description**: Professionals or assistants who help streamers create polished highlight reels.
   - **Needs**:
     - Efficient tools to extract and organize highlight moments.
     - Exportable lists or clips for further editing.
   - **Pain Points**:
     - Lack of streamlined workflows for processing large volumes of stream data.

### 3. **Platform Managers**
   - **Description**: Managers of streaming platforms or agencies analyzing trends and optimizing content.
   - **Needs**:
     - Aggregated data on high-performing moments across multiple streamers.
     - Insights into audience engagement patterns.
   - **Pain Points**:
     - Limited tools for large-scale analysis of stream data.

---

## Technical Path
### Technology Stack
- **Frontend**: React (for dynamic, modular GUI).
- **Backend**: Node.js (for lightweight API handling and data processing).
- **AI/ML**: TensorFlow or PyTorch (for highlight detection models).
- **Data Storage**: Browser local storage (initial) with scalability to cloud databases (e.g., Firebase, MongoDB).
- **Export Formats**: JSON for metadata, MP4 for video clips.

### Core Features
1. Automated highlight detection using AI/ML.
2. Customizable scoring system based on metrics like chat activity, audio peaks, and viewer count.
3. Filtering and sorting by game, category, and score.
4. Manual adjustment tools for fine-tuning highlights.
5. Export functionality for highlight lists or clips.

---

## Running the Project Locally
### Prerequisites
- Install Python (for running a local server).
- Clone the repository to your local machine.

### Steps
1. **Start a Local Server**:
   ```bash
   python -m http.server
   ```
   Open `http://localhost:8000` in your browser.

2. **Load the Application**:
   - Open `index.html` in the browser.

3. **Import Sample Data**:
   - Use the provided `data/sample_events.json` file.
   - Click the "Import" button and select the file or paste JSON data into the textarea.

4. **Interact with the Application**:
   - Use the filter controls to sort and filter highlights.
   - Add manual markers using the form.
   - Export the filtered results as a JSON file.

---

## Features and Usage
### 1. **Import**
   - Import stream data via file upload or JSON textarea.
   - Data is processed and displayed in the results panel.

### 2. **Scoring**
   - Each record is scored based on metrics like intensity, chat rate, and keywords.
   - Scores are calculated using the `scoreRecord` function in `src/core/scoring.js`.

### 3. **Filtering**
   - Filter highlights by streamer, game, category, or score.
   - Filters are applied using the `applyFilters` function in `src/core/filtering.js`.

### 4. **Manual Markers**
   - Add custom highlights using the manual marker form.
   - New records are appended to the dataset and displayed in the results panel.

### 5. **Export**
   - Export the current filtered results as a JSON file.
   - Uses `Blob` and `URL.createObjectURL` for file generation.

### 6. **Sample Data**
   - A sample dataset (`data/sample_events.json`) is included for testing and demonstration.

### 7. **Smoke Tests**
   - Run `tests/browser_smoke_test.js` to verify basic functionality.
   - Includes tests for importing, scoring, filtering, manual markers, and exporting.

---

## Example Workflow
1. **Import Data**:
   - Navigate to the Dashboard.
   - Click "Import Stream" and upload `sample_events.json`.

2. **Filter Highlights**:
   - Use the filter form to narrow down results by game or score.

3. **Edit Highlights**:
   - Open the Highlight Editor to adjust detected highlights or add manual markers.

4. **Export Highlights**:
   - Navigate to the Export Screen.
   - Select highlights and export them as a JSON file.

---

## Project Structure
### Key Files
- **Frontend**:
  - `index.html`: Main entry point.
  - `styles.css`: Styling for the application.
  - `src/ui/render.js`: Functions for rendering UI components.
  - `src/ui/forms.js`: Handles form interactions and bindings.
- **Backend**:
  - `src/core/scoring.js`: Scoring logic for highlights.
  - `src/core/filtering.js`: Filtering logic for highlights.
  - `src/core/importer.js`: Handles data import and normalization.
  - `src/core/exporter.js`: Handles data export functionality.
- **State Management**:
  - `src/state/store.js`: Manages local storage and application state.
- **Sample Data**:
  - `data/sample_events.json`: Example dataset for testing.
- **Tests**:
  - `tests/browser_smoke_test.js`: Basic smoke tests for the application.

---

## Testing
### Smoke Tests
- Verify that the application:
  - Imports data correctly.
  - Scores and sorts records.
  - Filters results based on user input.
  - Allows manual markers to be added.
  - Exports filtered results.

### Running Tests
- Open `tests/browser_smoke_test.js` in a browser or testing environment.
- Follow the test instructions to validate functionality.

---

## Future Enhancements
- **Cloud Storage**: Upgrade from local storage to a cloud-based database.
- **Advanced Analytics**: Add trend analysis and audience engagement insights.
- **Platform Integration**: Direct API integration with Twitch, YouTube, and Facebook Gaming.

---

## License
This project is licensed under the MIT License. See `LICENSE` for details.