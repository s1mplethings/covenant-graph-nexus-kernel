# TEST_PLAN.md

## Overview
This document outlines the test plan for the **Streamer Highlight Analyzer** project. The goal is to ensure the application meets functional, performance, and usability requirements. The tests cover core features such as data import, scoring, sorting, filtering, manual tagging, exporting, localStorage persistence, and error handling.

---

## Test Cases

### 1. Import Functionality
**Objective:** Verify that the application can import JSON data correctly.

- **Test Case 1.1:** Import JSON via file input.
  - **Steps:**
    1. Select a valid JSON file using the file input.
    2. Click the "Import" button.
    3. Verify that the data is displayed in the results panel.
  - **Expected Result:** Data is parsed and rendered correctly.

- **Test Case 1.2:** Import JSON via textarea.
  - **Steps:**
    1. Paste valid JSON data into the textarea.
    2. Click the "Import" button.
    3. Verify that the data is displayed in the results panel.
  - **Expected Result:** Data is parsed and rendered correctly.

- **Test Case 1.3:** Handle invalid JSON input.
  - **Steps:**
    1. Import a malformed JSON file or paste invalid JSON into the textarea.
    2. Click the "Import" button.
    3. Verify that an error message is displayed.
  - **Expected Result:** Error message is shown, and no data is imported.

---

### 2. Scoring Functionality
**Objective:** Ensure that the scoring function assigns accurate scores to records.

- **Test Case 2.1:** Verify scoring logic.
  - **Steps:**
    1. Import a dataset with known scoring criteria.
    2. Check the scores assigned to each record.
  - **Expected Result:** Scores match the expected values based on the scoring algorithm.

- **Test Case 2.2:** Verify sorting by score.
  - **Steps:**
    1. Import a dataset.
    2. Verify that records are sorted in descending order of scores.
  - **Expected Result:** Records are displayed in the correct order.

---

### 3. Filtering Functionality
**Objective:** Test the filtering controls for streamer, game, category, and score.

- **Test Case 3.1:** Filter by streamer.
  - **Steps:**
    1. Enter a streamer's name in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the streamer are displayed.

- **Test Case 3.2:** Filter by game.
  - **Steps:**
    1. Enter a game's name in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the game are displayed.

- **Test Case 3.3:** Filter by category.
  - **Steps:**
    1. Enter a category in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the category are displayed.

- **Test Case 3.4:** Filter by score range.
  - **Steps:**
    1. Enter a minimum and/or maximum score in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records within the score range are displayed.

---

### 4. Manual Marker Functionality
**Objective:** Verify that users can manually add highlights.

- **Test Case 4.1:** Add a manual highlight.
  - **Steps:**
    1. Fill out the manual marker form with valid data.
    2. Submit the form.
  - **Expected Result:** The new highlight is added to the dataset and displayed in the results panel.

- **Test Case 4.2:** Handle invalid manual input.
  - **Steps:**
    1. Submit the manual marker form with incomplete or invalid data.
  - **Expected Result:** An error message is displayed, and the highlight is not added.

---

### 5. Export Functionality
**Objective:** Ensure that filtered results can be exported correctly.

- **Test Case 5.1:** Export filtered results.
  - **Steps:**
    1. Apply filters to the dataset.
    2. Click the "Export" button.
    3. Verify that the exported file contains only the filtered results.
  - **Expected Result:** Exported file matches the filtered dataset.

- **Test Case 5.2:** Verify export format.
  - **Steps:**
    1. Export the dataset.
    2. Open the exported file and verify its format.
  - **Expected Result:** File is in valid JSON format.

---

### 6. LocalStorage Persistence
**Objective:** Test that working data is saved and restored using localStorage.

- **Test Case 6.1:** Save data to localStorage.
  - **Steps:**
    1. Import a dataset.
    2. Refresh the page.
  - **Expected Result:** Data is restored from localStorage.

- **Test Case 6.2:** Clear localStorage.
  - **Steps:**
    1. Clear the dataset using the "Clear" button.
    2. Refresh the page.
  - **Expected Result:** No data is restored.

---

### 7. Console Error Handling
**Objective:** Ensure that no unexpected errors are logged to the console.

- **Test Case 7.1:** Verify console output during normal operation.
  - **Steps:**
    1. Perform common tasks (import, filter, score, export).
    2. Check the browser console for errors.
  - **Expected Result:** No errors are logged.

- **Test Case 7.2:** Handle edge cases gracefully.
  - **Steps:**
    1. Perform edge case actions (e.g., import invalid data, apply invalid filters).
    2. Check the browser console for errors.
  - **Expected Result:** Errors are handled gracefully, and no unhandled exceptions are logged.

---

## Performance Testing
**Objective:** Ensure the application meets performance benchmarks.

- **Test Case 8.1:** Measure processing time for a 1-hour stream.
  - **Steps:**
    1. Import a dataset representing a 1-hour stream.
    2. Measure the time taken to process and display results.
  - **Expected Result:** Processing time is under 5 minutes.

---

## Usability Testing
**Objective:** Validate the application's usability with real users.

- **Test Case 9.1:** User testing with streamers.
  - **Steps:**
    1. Provide the application to streamers.
    2. Observe their interactions and gather feedback.
  - **Expected Result:** Users can complete key tasks (import, review, export) within 10 minutes.

- **Test Case 9.2:** User testing with editors.
  - **Steps:**
    1. Provide the application to content editors.
    2. Observe their interactions and gather feedback.
  - **Expected Result:** Users find the application intuitive and efficient.

---

## Summary
This test plan ensures comprehensive coverage of the application's functionality, performance, and usability. By following these test cases, we can validate that the **Streamer Highlight Analyzer** meets its quality standards and delivers value to its target users.