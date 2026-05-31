# TEST_PLAN.md

## Overview
This test plan outlines the testing strategy for the Streamer Highlight Tool, focusing on the core functionalities including import, scoring, sorting, filtering, manual marking, exporting, local storage, and ingestion of industrial input bundles.

## Test Objectives
- Validate the import functionality for various input formats.
- Ensure scoring and sorting algorithms work as expected.
- Test the filtering capabilities for streamer, game, category, and score.
- Verify the manual marker functionality.
- Confirm the export functionality produces the correct output.
- Test localStorage persistence and retrieval.
- Validate the ingestion of industrial input bundles.
- Ensure the expected output shape matches the specifications.
- Check source coverage for all functionalities.
- Monitor for console errors during operations.

## Test Cases

### 1. Import Functionality
- **Test Case ID**: TC_IMPORT_001
  - **Description**: Test importing a valid JSON file.
  - **Expected Result**: Records are correctly parsed and displayed.

- **Test Case ID**: TC_IMPORT_002
  - **Description**: Test importing an invalid JSON file.
  - **Expected Result**: Error message is displayed, and no records are imported.

### 2. Scoring Functionality
- **Test Case ID**: TC_SCORING_001
  - **Description**: Test scoring algorithm with sample records.
  - **Expected Result**: Records are scored correctly based on defined criteria.

### 3. Sorting Functionality
- **Test Case ID**: TC_SORTING_001
  - **Description**: Test sorting records by score in descending order.
  - **Expected Result**: Records are sorted correctly.

### 4. Filtering Functionality
- **Test Case ID**: TC_FILTERING_001
  - **Description**: Test filtering by streamer name.
  - **Expected Result**: Only records matching the streamer name are displayed.

- **Test Case ID**: TC_FILTERING_002
  - **Description**: Test filtering by game.
  - **Expected Result**: Only records matching the game are displayed.

- **Test Case ID**: TC_FILTERING_003
  - **Description**: Test filtering by category.
  - **Expected Result**: Only records matching the category are displayed.

- **Test Case ID**: TC_FILTERING_004
  - **Description**: Test filtering by score threshold.
  - **Expected Result**: Only records with scores above the threshold are displayed.

### 5. Manual Marker Functionality
- **Test Case ID**: TC_MANUAL_MARKER_001
  - **Description**: Test the manual marker input.
  - **Expected Result**: Manual markers are saved and displayed correctly.

### 6. Export Functionality
- **Test Case ID**: TC_EXPORT_001
  - **Description**: Test exporting the highlight list as JSON.
  - **Expected Result**: A downloadable JSON file is generated with the correct structure.

### 7. Local Storage Functionality
- **Test Case ID**: TC_LOCAL_STORAGE_001
  - **Description**: Test saving records to localStorage.
  - **Expected Result**: Records are saved and can be retrieved after a page reload.

### 8. Industrial Input Bundle Ingestion
- **Test Case ID**: TC_INPUT_BUNDLE_001
  - **Description**: Test ingestion of an industrial input bundle.
  - **Expected Result**: Records are correctly parsed and displayed.

### 9. Expected Output Shape
- **Test Case ID**: TC_OUTPUT_SHAPE_001
  - **Description**: Validate the output shape against the expected schema.
  - **Expected Result**: Output matches the expected shape defined in the specifications.

### 10. Source Coverage
- **Test Case ID**: TC_SOURCE_COVERAGE_001
  - **Description**: Check that all source files are covered by tests.
  - **Expected Result**: All source files have corresponding tests.

### 11. Console Errors
- **Test Case ID**: TC_CONSOLE_ERRORS_001
  - **Description**: Monitor console for errors during operations.
  - **Expected Result**: No console errors should appear during normal operation.

## Conclusion
This test plan serves as a comprehensive guide to ensure the Streamer Highlight Tool meets its functional requirements and provides a seamless experience for users. Each test case is designed to validate a specific aspect of the tool, ensuring robustness and reliability.