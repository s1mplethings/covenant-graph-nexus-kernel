# TEST_PLAN.md

## Test Plan for Highlight Finder Application

This document outlines the test cases for verifying the functionality of the Highlight Finder application. The application is designed to help users import live event data, score and sort records, filter results, manually mark highlights, export filtered data, persist data locally, and ensure error-free operation.

---

### 1. Import Functionality
**Objective:** Verify that the application can import JSON data via file input or textarea.

- **Test Case 1.1:** Import JSON file using file input (`file-input`).
  - **Steps:**
    1. Click on the file input element.
    2. Select a valid JSON file.
    3. Click the "Import" button (`import-button`).
  - **Expected Result:** Data is parsed and displayed in the records container (`records-container`).

- **Test Case 1.2:** Import JSON data via textarea (`json-textarea`).
  - **Steps:**
    1. Paste valid JSON data into the textarea.
    2. Click the "Import" button (`import-button`).
  - **Expected Result:** Data is parsed and displayed in the records container (`records-container`).

---

### 2. Scoring Functionality
**Objective:** Verify that the application assigns scores to imported records.

- **Test Case 2.1:** Validate scoring logic.
  - **Steps:**
    1. Import a dataset with known attributes (e.g., intensity, chatRate, keywords).
    2. Check the scores assigned to each record.
  - **Expected Result:** Scores are calculated correctly based on the scoring function.

---

### 3. Sorting Functionality
**Objective:** Verify that records are sorted by score in descending order.

- **Test Case 3.1:** Validate sorting logic.
  - **Steps:**
    1. Import a dataset with varying scores.
    2. Check the order of records in the records container (`records-container`).
  - **Expected Result:** Records are sorted by score in descending order.

---

### 4. Filter Functionality
**Objective:** Verify that filters for streamer, game, category, and score work as expected.

- **Test Case 4.1:** Filter by streamer (`filterStreamer`).
  - **Steps:**
    1. Enter a streamer name in the filter form (`filter-form`).
    2. Submit the filter form.
  - **Expected Result:** Only records matching the streamer name are displayed.

- **Test Case 4.2:** Filter by game (`filterGame`).
  - **Steps:**
    1. Enter a game name in the filter form (`filter-form`).
    2. Submit the filter form.
  - **Expected Result:** Only records matching the game name are displayed.

- **Test Case 4.3:** Filter by category (`filterCategory`).
  - **Steps:**
    1. Enter a category name in the filter form (`filter-form`).
    2. Submit the filter form.
  - **Expected Result:** Only records matching the category are displayed.

- **Test Case 4.4:** Filter by score (`filterScore`).
  - **Steps:**
    1. Enter a minimum score in the filter form (`filter-form`).
    2. Submit the filter form.
  - **Expected Result:** Only records with scores above the minimum are displayed.

---

### 5. Manual Marker Functionality
**Objective:** Verify that users can manually add records to the dataset.

- **Test Case 5.1:** Add a manual record (`manual-form`).
  - **Steps:**
    1. Fill out the manual marker form with valid data.
    2. Submit the form.
  - **Expected Result:** The new record is appended to the dataset and displayed in the records container (`records-container`).

---

### 6. Export Functionality
**Objective:** Verify that filtered results can be exported as a JSON file.

- **Test Case 6.1:** Export filtered results (`export-button`).
  - **Steps:**
    1. Apply filters to the dataset.
    2. Click the "Export" button (`export-button`).
  - **Expected Result:** A JSON file containing the filtered results is downloaded.

---

### 7. LocalStorage Functionality
**Objective:** Verify that working data is persisted in localStorage and restored on page reload.

- **Test Case 7.1:** Persist data to localStorage.
  - **Steps:**
    1. Import a dataset.
    2. Reload the page.
  - **Expected Result:** The dataset is restored from localStorage and displayed in the records container (`records-container`).

---

### 8. Console Error Checks
**Objective:** Ensure that the application runs without console errors.

- **Test Case 8.1:** Check for console errors during normal operation.
  - **Steps:**
    1. Perform all major actions (import, filter, score, sort, manual marker, export).
    2. Monitor the browser console.
  - **Expected Result:** No errors are logged in the console.

---

### 9. Edge Cases
**Objective:** Test edge cases to ensure robustness.

- **Test Case 9.1:** Import invalid JSON data.
  - **Expected Result:** An error message is displayed, and no data is imported.

- **Test Case 9.2:** Apply filters with no matching records.
  - **Expected Result:** The records container (`records-container`) is empty.

- **Test Case 9.3:** Export with no filtered results.
  - **Expected Result:** An empty JSON file is downloaded.

---

### 10. Performance Checks
**Objective:** Verify that the application performs well with large datasets.

- **Test Case 10.1:** Import and process a large dataset.
  - **Expected Result:** The application remains responsive, and all functionalities work as expected.

---

### 11. Accessibility Checks
**Objective:** Ensure the application is accessible to all users.

- **Test Case 11.1:** Verify keyboard navigation.
  - **Expected Result:** All interactive elements are accessible via keyboard.

- **Test Case 11.2:** Verify screen reader compatibility.
  - **Expected Result:** All elements are properly labeled and readable by screen readers.

---

### Summary
This test plan covers all major functionalities of the Highlight Finder application, ensuring that it meets the specified requirements and performs reliably for the target users.