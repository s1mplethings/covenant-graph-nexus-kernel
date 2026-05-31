# Game Stream Highlight Finder

This project is designed to help game streamers, content editors, and live stream operators identify and manage highlight moments from game streams. It allows users to import live stream event data, automatically score and sort highlights, filter by various criteria, manually mark highlights, export a list of clips, and generate a test effect report.

## Features

- **Data Import**: Import live stream event data via a JSON file or a textarea input.
- **Automatic Scoring**: Automatically score events based on intensity, chat rate, keywords, and other factors.
- **Sorting**: Sort detected highlights by score in descending order.
- **Filtering**: Filter highlights by streamer, game, category, and score.
- **Manual Marking**: Add custom highlights manually through a form.
- **Export**: Export the filtered highlights as a downloadable JSON file.
- **Persistence**: Save and restore working data using `localStorage`.

## How to Run Locally

1. Clone or download the repository to your local machine.
2. Navigate to the project directory in your terminal.
3. Start a local server using Python:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000`.
5. Use the application to import data, score events, filter results, and manage highlights.

## Usage Instructions

1. **Import Data**:
   - Use the "Import Data" button to upload a JSON file or paste JSON data into the provided textarea.
   - The app will process the data and display scored highlights.

2. **Filter Highlights**:
   - Use the filter controls to narrow down results by streamer, game, category, or score range.

3. **Add Manual Highlights**:
   - Fill out the manual marker form to add a custom highlight. The new highlight will be appended to the dataset and displayed in the results.

4. **Export Highlights**:
   - Click the "Export" button to download the current filtered highlights as a JSON file.

5. **Persistence**:
   - The app automatically saves your working data to `localStorage`. When you reload the page, your data will be restored.

## Project Structure

- `index.html`: The main HTML file containing the UI structure.
- `app.js`: The core JavaScript file implementing the app's logic, including scoring, filtering, and exporting.
- `style.css`: The stylesheet for the app's UI.

## Dependencies

This project uses only vanilla JavaScript, HTML, and CSS. No external libraries or frameworks are required.

## Notes

- Ensure your browser supports `localStorage` and `FileReader` for full functionality.
- For testing purposes, sample JSON data can be used to simulate live stream events.

Enjoy finding and managing your game stream highlights!