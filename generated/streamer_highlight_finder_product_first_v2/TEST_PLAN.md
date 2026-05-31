# TEST_PLAN.md

## Overview
This document outlines the testing plan for the "Streamer Highlight Analyzer" project. The tests cover core functionalities, including data import, scoring, sorting, filtering, manual marking, exporting, localStorage persistence, and error handling.

---

## Test Cases

### 1. Import Functionality
#### Objective:
Verify that the application can successfully import JSON data via file input or textarea.

#### Steps:
1. Provide a valid JSON file containing stream event data.
2. Use the file input or textarea to import the data.
3. Verify that the imported data is parsed and displayed in the application.

#### Expected Results:
- Imported data is normalized and displayed in the records container.
- Invalid JSON triggers an error message in the status summary.

---

### 2. Scoring Functionality
#### Objective:
Ensure that the scoring function assigns numeric scores to imported records based on predefined criteria.

#### Steps:
1. Import sample data with various intensity, chatRate, and keywords.
2. Verify that each record is assigned a score.
3. Check that scores are calculated correctly based on the scoring algorithm.

#### Expected Results:
- Scores are numeric and reflect the criteria defined in the scoring function.
- Records with higher engagement metrics receive higher scores.

---

### 3. Sorting Functionality
#### Objective:
Validate that records are sorted by score in descending order.

#### Steps:
1. Import sample data with varying scores.
2. Verify that records are displayed in descending order of score.

#### Expected Results:
- Records are sorted correctly, with the highest score appearing first.

---

### 4. Filtering Functionality
#### Objective:
Test the filtering controls for streamer, game, category, and score.

#### Steps:
1. Import sample data containing multiple streamers, games, categories, and scores.
2. Apply filters using the filter form.
3. Verify that only records matching the filter criteria are displayed.

#### Expected Results:
- Filters correctly narrow down the displayed records.
- Invalid filter inputs trigger an error message.

---

### 5. Manual Marker Functionality
#### Objective:
Ensure users can manually add highlights and update the dataset.

#### Steps:
1. Use the manual marker form to add a new highlight.
2. Verify that the new highlight is appended to the dataset.
3. Check that the records container is updated to include the new highlight.

#### Expected Results:
- Manually added highlights appear in the records container.
- The dataset is updated and persists across page reloads.

---

### 6. Export Functionality
#### Objective:
Validate the export functionality for filtered results.

#### Steps:
1. Apply filters to narrow down the dataset.
2. Use the export button to download the filtered results.
3. Verify that the exported file contains the correct data.

#### Expected Results:
- Exported file matches the filtered dataset.
- File is downloadable in JSON format.

---

### 7. LocalStorage Persistence
#### Objective:
Ensure that working data persists locally and reloads on page load.

#### Steps:
1. Import data and apply filters.
2. Reload the page.
3. Verify that the data and filters are restored from localStorage.

#### Expected Results:
- Data and filters persist across page reloads.
- Clearing localStorage removes all stored data.

---

### 8. Console Error Handling
#### Objective:
Check for unhandled errors or warnings in the browser console.

#### Steps:
1. Perform various actions (import, filter, score, sort, export, manual marking).
2. Monitor the browser console for errors or warnings.

#### Expected Results:
- No unhandled errors or warnings appear in the console.
- Any errors are logged with clear messages for debugging.

---

## Performance Testing

### 9. Processing Time
#### Objective:
Measure the time taken to process a 1-hour stream.

#### Steps:
1. Import a dataset representing a 1-hour stream.
2. Record the time taken for scoring, sorting, and rendering.

#### Expected Results:
- Processing time is under 5 minutes on a standard machine.

---

## Usability Testing

### 10. User Workflow Validation
#### Objective:
Ensure users can complete key tasks within 10 minutes.

#### Steps:
1. Import data, review highlights, apply filters, manually mark highlights, and export results.
2. Gather feedback from streamers and editors.

#### Expected Results:
- Users complete tasks efficiently and without confusion.
- Feedback indicates high usability.

---

## Integration Testing

### 11. End-to-End Data Flow
#### Objective:
Verify seamless integration between modules.

#### Steps:
1. Import data and process it through scoring, sorting, filtering, manual marking, and exporting.
2. Check that data flows correctly between modules.

#### Expected Results:
- Data flows seamlessly from import to export.
- No data loss or corruption occurs.

---

## Acceptance Criteria Validation
#### Objective:
Ensure the application meets all acceptance criteria.

#### Steps:
1. Test each acceptance criterion as outlined in the project plan.
2. Verify compliance with functional and non-functional requirements.

#### Expected Results:
- All acceptance criteria are met.
- The application is ready for deployment.

---

## Test Environment
- Browser: Latest version of Chrome, Firefox, and Edge.
- OS: Windows 10, macOS, and Linux.
- Tools: Developer console, JSON validator, stopwatch for performance testing.

---

## Reporting
- Document test results in a structured format.
- Highlight any issues or deviations from expected results.
- Provide recommendations for fixes or improvements.

---

## Conclusion
This testing plan ensures comprehensive coverage of all core functionalities and user workflows. Successful execution of these tests will validate the application's readiness for deployment.