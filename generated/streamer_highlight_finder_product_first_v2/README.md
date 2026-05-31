# Streamer Highlight Analyzer

## Purpose
The **Streamer Highlight Analyzer** is a web-based application designed to help gaming streamers, content editors, and platform analysts identify, score, and manage highlights from gaming streams. By automating the detection of engaging moments and providing tools for manual adjustments, the application streamlines the process of creating highlight reels and analyzing streamer performance.

## Target Users
1. **Streamers**: Content creators who want to identify their most engaging moments to improve their content strategy or create highlight reels.
2. **Content Editors**: Professionals or hobbyists assisting streamers in creating polished highlight reels.
3. **Platform Analysts**: Individuals or teams analyzing streamer performance for platforms or agencies.

## Selected Technical Path
The project uses the following technical stack:
- **Frontend**: React - for building a dynamic and scalable user interface.
- **Backend**: Node.js - for lightweight and efficient data processing.
- **Machine Learning**: TensorFlow.js - for in-browser highlight detection without server-side processing.
- **Data Storage**: Browser local storage - simplifies initial implementation and can be upgraded later.

## How to Run the Project Locally
1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/streamer-highlight-analyzer.git
   cd streamer-highlight-analyzer
   ```
2. Start a local server:
   ```bash
   python -m http.server
   ```
3. Open the application in your browser:
   - Navigate to `http://localhost:8000` (or the port specified by your server).

## Features and Usage

### Import
- **How to Import Data**: 
  - Use the file input or JSON textarea to upload stream event data.
  - Click the "Import" button to process the data.
- **Supported Format**: JSON with fields such as `streamer`, `game`, `timestamp`, `category`, `score`, etc.

### Scoring
- **Automated Scoring**: 
  - The application assigns scores to highlights based on engagement metrics like chat rate, intensity, and keywords.
- **Customization**: 
  - Adjust scoring criteria via the settings panel (future feature).

### Filtering
- **Filter Options**:
  - Filter highlights by streamer, game, category, or score.
- **How to Apply Filters**:
  - Use the filter form to specify criteria and click "Apply Filters."

### Manual Markers
- **Adding Highlights**:
  - Use the manual marker form to add custom highlights.
  - Provide details like title, description, and score.
- **Updating Dataset**:
  - Newly added highlights are appended to the dataset and displayed immediately.

### Export
- **Exporting Highlights**:
  - Filtered highlights can be exported as JSON files.
  - Click the "Export" button to download the file.
- **Supported Formats**:
  - JSON (future support for CSV or other formats).

### Sample Data
- **Included Sample Data**:
  - The project includes `data/sample_events.json` for testing and demonstration purposes.
- **How to Use**:
  - Import the sample data via the file input or textarea to explore the application's functionality.

### Smoke Tests
- **Purpose**:
  - Verify basic functionality and ensure the application runs as expected.
- **How to Run**:
  - Open `tests/browser_smoke_test.js` in your browser console or testing environment.
  - Follow the instructions to execute smoke tests.

## Project Structure
- **Frontend**: Handles user interface and interactions.
- **Backend**: Processes data and manages scoring/filtering logic.
- **Machine Learning Models**: Detect highlights using TensorFlow.js.
- **Utilities**: Manage local storage, data export, and other helper functions.

## Contribution
Feel free to contribute by submitting issues or pull requests. For major changes, please open an issue first to discuss what you would like to change.

## License
This project is licensed under the MIT License. See the LICENSE file for details.