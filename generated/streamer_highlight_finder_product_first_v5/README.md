# Streamer Highlight Analyzer

## Purpose
The **Streamer Highlight Analyzer** is a lightweight, browser-based application designed to help gaming streamers, content editors, and platform analysts identify, score, and manage highlights from gaming streams. The tool provides automated scoring, filtering, and manual tagging capabilities, enabling users to efficiently extract and export the most engaging moments from their streams.

## Target Users
1. **Streamers**: Content creators who want to identify their most engaging moments to create highlight reels or improve their content strategy.
2. **Content Editors**: Professionals or hobbyists assisting streamers in creating polished highlight reels.
3. **Platform Analysts**: Individuals or teams analyzing streamer performance for platforms or agencies.

## Technical Path
This project is implemented as a **static browser application** with the following characteristics:
- **No external dependencies**: No React, Node.js, or npm is required.
- **Frontend-only architecture**: All logic is implemented in vanilla JavaScript, HTML, and CSS.
- **Local storage**: Data is stored and persisted using the browser's `localStorage`.
- **Execution**: The app runs locally using Python's built-in HTTP server.

## How to Run the Project Locally
1. Clone or download the project directory to your local machine.
2. Open a terminal and navigate to the project directory.
3. Run the following command to start a local HTTP server:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000`.
5. The application will load, and you can begin using it.

## Features and Usage

### 1. Import
- **How to Use**: 
  - Use the file input or paste JSON data into the provided textarea.
  - Click the "Import" button to load the data into the application.
- **Supported Format**: JSON data with fields such as `streamer`, `game`, `timestamp`, `category`, `intensity`, `chatRate`, `keywords`, `title`, `description`, and `score`.

### 2. Scoring
- **How It Works**: 
  - The app automatically assigns a score to each record based on predefined criteria (e.g., intensity, chat rate, keywords).
  - Scores are calculated using a JavaScript function and sorted in descending order.

### 3. Filtering
- **How to Use**: 
  - Use the filter form to narrow down results by `streamer`, `game`, `category`, or `score`.
  - Apply filters to dynamically update the displayed highlights.

### 4. Manual Markers
- **How to Use**: 
  - Use the manual marker form to add custom highlights.
  - Fill in the required fields (e.g., title, description, score) and submit the form.
  - The new highlight will be appended to the dataset and displayed in the results.

### 5. Export
- **How to Use**: 
  - Click the "Export" button to download the current filtered results as a JSON file.
  - The export functionality uses the browser's `Blob` and `URL.createObjectURL` APIs.

### 6. Sample Data
- **How to Use**: 
  - A sample dataset is provided in `data/sample_events.json`.
  - Import this file to explore the application's features.

### 7. Smoke Tests
- **How to Run**: 
  - Open the `tests/browser_smoke_test.js` file in a browser console.
  - The script will simulate basic user interactions to verify the app's functionality.

## Project Structure
- **HTML**: `index.html` - The main entry point for the application.
- **CSS**: `styles.css` - Styles for the user interface.
- **JavaScript**:
  - `src/core/`: Core logic for scoring, filtering, importing, and exporting.
  - `src/state/`: State management and local storage utilities.
  - `src/ui/`: Rendering and form handling.
  - `src/app.js`: Main application logic.
- **Data**: `data/sample_events.json` - Sample dataset for testing.
- **Tests**: `tests/browser_smoke_test.js` - Smoke test script.

## Summary
The **Streamer Highlight Analyzer** is a modular, easy-to-use tool for identifying and managing gaming stream highlights. With its local execution model and browser-based architecture, it provides a lightweight yet powerful solution for streamers, editors, and analysts. Follow the steps above to run the project locally and explore its features.