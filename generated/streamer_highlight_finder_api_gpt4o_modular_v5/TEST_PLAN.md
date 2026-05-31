# TEST_PLAN.md

## Overview
This document outlines the test plan for the **Game Stream Highlight Detector** project. The tests are designed to ensure the functionality, reliability, and performance of the application, covering all modules and user interactions.

---

## Test Cases

### 1. Import Functionality
**Objective:** Verify that the application can import data from JSON files and textarea input.

- **Test Case 1.1:** Import valid JSON file via file input.
  - **Steps:**
    1. Select a valid JSON file using the file input.
    2. Click the "Import" button.
  - **Expected Result:** Data is parsed and displayed in the records container.
  
- **Test Case 1.2:** Import invalid JSON file.
  - **Steps:**
    1. Select an invalid JSON file.
    2. Click the "Import" button.
  - **Expected Result:** An error message is displayed, and no data is imported.

- **Test Case 1.3:** Import JSON data via textarea.
  - **Steps:**
    1. Paste valid JSON data into the textarea.
    2. Click the "Import" button.
  - **Expected Result:** Data is parsed and displayed in the records container.

---

### 2. Scoring Functionality
**Objective:** Ensure that records are scored correctly based on the scoring logic.

- **Test Case 2.1:** Verify scoring logic.
  - **Steps:**
    1. Import a dataset with known values for intensity, chatRate, and other scoring factors.
    2. Check the calculated scores.
  - **Expected Result:** Scores match the expected values based on the scoring algorithm.

---

### 3. Sorting Functionality
**Objective:** Verify that records are sorted by score in descending order.

- **Test Case 3.1:** Sort records by score.
  - **Steps:**
    1. Import a dataset with varying scores.
    2. Check the order of records in the records container.
  - **Expected Result:** Records are sorted by score in descending order.

---

### 4. Filter Functionality
**Objective:** Ensure that filters for streamer, game, category, and score work as expected.

- **Test Case 4.1:** Filter by streamer.
  - **Steps:**
    1. Enter a streamer's name in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the streamer's name are displayed.

- **Test Case 4.2:** Filter by game.
  - **Steps:**
    1. Enter a game's name in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the game's name are displayed.

- **Test Case 4.3:** Filter by category.
  - **Steps:**
    1. Select a category from the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records matching the category are displayed.

- **Test Case 4.4:** Filter by score range.
  - **Steps:**
    1. Enter a minimum and/or maximum score in the filter form.
    2. Apply the filter.
  - **Expected Result:** Only records within the score range are displayed.

---

### 5. Manual Marker Functionality
**Objective:** Verify that users can manually add highlights to the dataset.

- **Test Case 5.1:** Add a manual highlight.
  - **Steps:**
    1. Fill out the manual marker form with valid data.
    2. Submit the form.
  - **Expected Result:** The new record is added to the dataset and displayed in the records container.

---

### 6. Export Functionality
**Objective:** Ensure that filtered highlights can be exported as a downloadable file.

- **Test Case 6.1:** Export filtered highlights.
  - **Steps:**
    1. Apply filters to the dataset.
    2. Click the "Export" button.
  - **Expected Result:** A JSON file containing the filtered highlights is downloaded.

---

### 7. LocalStorage Functionality
**Objective:** Verify that data is persisted in localStorage and reloaded on page load.

- **Test Case 7.1:** Save data to localStorage.
  - **Steps:**
    1. Import a dataset.
    2. Refresh the page.
  - **Expected Result:** The dataset is reloaded from localStorage.

- **Test Case 7.2:** Clear localStorage.
  - **Steps:**
    1. Clear the dataset using the UI.
    2. Refresh the page.
  - **Expected Result:** No data is loaded from localStorage.

---

### 8. Console Error Checks
**Objective:** Ensure that no errors are logged to the console during normal operation.

- **Test Case 8.1:** Perform all major actions.
  - **Steps:**
    1. Import data.
    2. Apply filters.
    3. Add a manual highlight.
    4. Export data.
    5. Refresh the page.
  - **Expected Result:** No errors are logged to the console.

---

## Test Strategy
1. **Unit Tests:** Test individual modules for correctness.
2. **Integration Tests:** Verify that modules work together as expected.
3. **UI Tests:** Ensure that user interactions are functional and intuitive.
4. **Performance Tests:** Validate the application's performance with large datasets.
5. **Acceptance Tests:** Confirm that all acceptance criteria are met.

---

## Test Environment
- **Browser:** Latest versions of Chrome, Firefox, and Edge.
- **Server:** Local server using `python -m http.server`.
- **Test Data:** `data/sample_events.json`.

---

## Test Execution
- **Tools:** Manual testing, browser developer tools, and automated test scripts.
- **Frequency:** Tests will be executed after each major development milestone.

---

## Reporting
- Test results will be documented in the `test_report_screen` and exported as a JSON file for review.