# Game Stream Highlight Finder

This project is a web-based tool designed to help game streamers, content editors, and live stream operators identify and manage highlight moments from live stream event data. It allows users to import event data, automatically score and sort highlights, filter results, manually mark highlights, export a list of clips, and generate a test effect report.

## Features

- **Data Import**: Import JSON data via file upload or textarea input.
- **Automatic Scoring**: Automatically score and sort events based on intensity, chat rate, and other metrics.
- **Filtering**: Filter highlights by streamer, game, category, and score.
- **Manual Marking**: Add custom highlights manually through a form.
- **Export**: Export the filtered highlight list as a downloadable JSON file.
- **Persistence**: Save and reload working data using browser localStorage.

## How to Run Locally

1. Clone the repository or download the project files.
2. Open a terminal in the project directory.
3. Start a local server using Python:
   ```bash
   python -m http.server
   ```
4. Open your browser and navigate to `http://localhost:8000`.
5. Use the interface to import data, manage highlights, and export results.

## Usage Instructions

1. **Import Data**:
   - Use the file input or paste JSON data into the textarea.
   - Click the "Import" button to load the data into the app.

2. **Filter Highlights**:
   - Use the filter form to narrow down results by streamer, game, category, or minimum score.
   - The results will update dynamically.

3. **Add Manual Highlights**:
   - Fill out the manual marker form with the required fields.
   - Submit the form to add a new highlight to the dataset.

4. **Export Results**:
   - Click the "Export" button to download the current filtered results as a JSON file.

5. **Persistence**:
   - The app automatically saves your working data to localStorage.
   - Reload the page to restore your data.

## File Structure

- `index.html`: The main HTML file containing the app's structure and UI.
- `app.js`: The JavaScript file implementing the app's logic, including scoring, filtering, and exporting.
- `style.css`: The CSS file for styling the app.

## Requirements

- A modern web browser with JavaScript enabled.
- Python 3.x for running the local server.

## Example Data Format

```json
[
  {
    "streamer": "StreamerName",
    "game": "GameTitle",
    "timestamp": "2023-01-01T12:00:00Z",
    "category": "Epic Kill",
    "intensity": 95,
    "chatRate": 120,
    "keywords": ["kill", "headshot"],
    "title": "Amazing Headshot",
    "description": "A perfect headshot during the final match.",
    "score": 0
  }
]
```

## Contributing

Feel free to fork this repository and submit pull requests for improvements or new features.

## License

This project is licensed under the MIT License.