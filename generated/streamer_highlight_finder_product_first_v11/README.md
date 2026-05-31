# Game Stream Highlight Detector

## Purpose
The **Game Stream Highlight Detector** is a browser-based tool designed to help game streamers, content editors, and platform managers efficiently identify, score, filter, and export high-impact moments from live streams. By automating the process of highlight detection and providing intuitive tools for manual editing and filtering, this tool saves time and enhances the quality of content shared on social media platforms.

## Target Users
1. **Game Streamers**  
   - Identify high-impact moments in their streams.
   - Improve content quality and engagement.
   - Save time on manual review and editing.

2. **Content Editors**  
   - Streamline the process of finding and editing highlight clips.
   - Collaborate with streamers to produce engaging content.
   - Export clips for social media platforms.

3. **Platform Managers**  
   - Provide tools for streamers to enhance their content.
   - Increase platform engagement and retention.
   - Support monetization strategies through high-quality clips.

## Technical Path
This project is implemented as a **local static browser application**. It does not require external dependencies, React, or a Node.js backend. All data is processed and stored locally using browser APIs, ensuring simplicity and ease of use.

### Key Technologies
- **HTML, CSS, and JavaScript** for the frontend.
- **Browser LocalStorage** for data persistence.
- **Modular JavaScript** for scoring, filtering, importing, exporting, and rendering.

## How to Run the Project Locally
1. Clone or download the project files to your local machine.
2. Navigate to the project directory in your terminal.
3. Run the following command to start a local server:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000`.
5. The application will load, and you can begin using it immediately.

## Features and Usage

### 1. Import
- **How to Use**:  
  - Use the file input or JSON textarea to upload live stream event data in JSON format.
  - Click the "Import" button to process the data.
- **Functionality**:  
  - Parses and normalizes the imported data.
  - Stores the data in the browser's local storage for further processing.

### 2. Scoring
- **How to Use**:  
  - Imported records are automatically scored based on predefined criteria (e.g., intensity, chat rate, keywords).
- **Functionality**:  
  - Assigns a numeric score to each record.
  - Sorts records in descending order of their scores.

### 3. Filtering
- **How to Use**:  
  - Use the filter form to specify criteria such as streamer, game, category, or minimum score.
  - Submit the form to apply the filters.
- **Functionality**:  
  - Filters the dataset based on the selected criteria.
  - Displays only the matching records.

### 4. Manual Markers
- **How to Use**:  
  - Fill out the manual marker form with details of a new highlight.
  - Submit the form to add the new highlight to the dataset.
- **Functionality**:  
  - Appends the new record to the working dataset.
  - Rerenders the results to include the new highlight.

### 5. Export
- **How to Use**:  
  - Click the "Export" button to download the current filtered dataset as a JSON file.
- **Functionality**:  
  - Uses the browser's Blob API to create a downloadable file.
  - Includes only the records that match the current filters.

### 6. Sample Data
- **How to Use**:  
  - Load the provided sample data (`data/sample_events.json`) to explore the application's features.
- **Functionality**:  
  - Demonstrates the scoring, filtering, and export capabilities with preloaded data.

### 7. Smoke Tests
- **How to Use**:  
  - Run the provided browser smoke test script (`tests/browser_smoke_test.js`) to validate basic functionality.
- **Functionality**:  
  - Ensures that key features such as importing, scoring, filtering, manual markers, and exporting work as expected.

## Project Structure
- **`index.html`**: Main entry point for the application.
- **`styles.css`**: Stylesheet for the user interface.
- **`src/`**: Contains modular JavaScript files for core functionality.
  - `core/`: Scoring, filtering, importing, and exporting logic.
  - `state/`: Local storage management.
  - `ui/`: Rendering and form handling.
- **`data/`**: Sample data for testing.
- **`tests/`**: Smoke test scripts for functionality validation.

## Summary
The **Game Stream Highlight Detector** is a lightweight, modular tool that runs entirely in the browser. It provides an intuitive interface for importing, scoring, filtering, manually marking, and exporting highlights from game streams. With no external dependencies, it is easy to set up and use, making it an ideal solution for streamers, editors, and platform managers looking to enhance their content creation workflows.