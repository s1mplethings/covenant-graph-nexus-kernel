# Streamer Highlight Tool

## Product Purpose
The **Streamer Highlight Tool** is designed for game streamers and content creators to automatically identify highlight segments from a single video file. It provides a timeline of highlights and a downloadable clip list, streamlining the process of content creation and management.

## Target Users
The primary users of this tool are:
- Game streamers
- Content editors
- Live operation personnel

These users require efficient methods to extract and manage highlight clips from gameplay videos.

## Selected Technical Path
The project is implemented as a local static browser application, ensuring ease of use without the need for complex setups. Key technical choices include:
- **No external dependencies**: The application runs entirely in the browser.
- **Local storage**: Highlight data is saved using the browser's localStorage.
- **Blob JSON export**: Users can export their data in JSON format.
- **No backend**: The application does not require a Node.js backend.

## Running the Project Locally
To run the project locally, follow these steps:
1. Navigate to the project directory in your terminal.
2. Execute the following command:
   ```bash
   python -m http.server
   ```
3. Open your web browser and go to `http://localhost:8000` to access the application.

## Using the Application

### Importing Data
- **Textarea/File JSON Import**: Users can import highlight data either by pasting JSON into a textarea or by uploading a JSON file.
- **Industrial Input Bundle Import**: The application supports importing a predefined industrial input bundle from `data/industrial_input_bundle.json`.

### Scoring
- The tool allows users to score highlight segments based on predefined criteria. The scoring function ranks highlights and sorts them in descending order.

### Filtering
- Users can filter highlights based on:
  - Streamer
  - Game
  - Category
  - Minimum score

### Manual Markers
- Users can add manual markers to highlight segments through a dedicated form, allowing for custom annotations.

### Exporting Data
- **Blob JSON Export**: Users can export their highlight data as a JSON file, which can be downloaded directly from the browser.

### Sample Data
- Sample data for testing can be found in `data/sample_events.json`, which provides a structured format for highlight records.

### Industrial Input Bundle
- The industrial input bundle is located at `data/industrial_input_bundle.json` and simulates inputs from various resource categories, including platform event logs and chat analytics.

### Expected Outputs
- The expected outputs of the application can be found in `data/expected_outputs.json`, detailing the structure and content of the generated highlight data.

### Smoke Tests
- Smoke tests are included to ensure the application functions as expected. These can be found in `tests/browser_smoke_test.js` and `tests/industrial_io_smoke_test.js`.

## Conclusion
The Streamer Highlight Tool is a powerful and user-friendly application designed to assist game streamers and content creators in managing their highlight clips efficiently. With its straightforward import/export capabilities and robust filtering options, it serves as an essential tool for enhancing content creation workflows.