# UX and GUI Design Specification for Game Stream Highlight Identifier

## Information Architecture

The application is structured into distinct modules and screens to ensure clarity and usability. The primary components include:

1. **Home Screen**: 
   - Purpose: Entry point for users to import industrial input bundles and access processed highlights.
   - Key Elements: File input, JSON textarea, import button, and status summary.

2. **Highlight View Screen**:
   - Purpose: Displays scored and sorted highlights with filtering and tagging options.
   - Key Elements: Filter controls, result cards, manual tagging form, and action bar.

3. **Export Screen**:
   - Purpose: Allows users to export filtered highlights as JSON or CSV files.
   - Key Elements: Export button and summary of selected highlights.

The information architecture ensures that users can seamlessly navigate between importing data, analyzing highlights, and exporting results.

---

## Primary Screen Layout

The primary screen layout is divided into the following sections:

1. **Header**:
   - Class: `app-header`
   - Purpose: Displays the application title and provides quick access to navigation links.

2. **Workspace Grid**:
   - Class: `workspace-grid`
   - Purpose: Organizes the main content into panels for data intake, filtering, results, and manual tagging.

3. **Panels**:
   - **Intake Panel**:
     - Class: `intake-panel`
     - Contains: File input (`file-input`), JSON textarea (`json-textarea`), and import button (`import-button`).
   - **Filters Panel**:
     - Class: `filters-panel`
     - Contains: Filter form (`filter-form`) with fields for streamer, game, category, and score.
   - **Results Panel**:
     - Class: `results-panel`
     - Displays: Highlight cards (`highlight-card`) with metadata and scores.
   - **Manual Panel**:
     - Class: `manual-panel`
     - Contains: Manual tagging form (`manual-form`) for adding new highlights.

4. **Status Strip**:
   - Class: `status-strip`
   - Purpose: Displays processing status and summary of results.

5. **Action Bar**:
   - Class: `action-bar`
   - Purpose: Provides export functionality via the export button (`export-button`).

---

## Control Grouping

Controls are grouped based on their functionality:

1. **Data Intake**:
   - File input, JSON textarea, and import button are grouped in the `intake-panel`.

2. **Filtering**:
   - Filter controls for streamer, game, category, and score are grouped in the `filters-panel`.

3. **Results Interaction**:
   - Highlight cards and manual tagging form are grouped in the `results-panel` and `manual-panel`.

4. **Export**:
   - Export button is located in the `action-bar` for easy access.

---

## Empty, Loading, and Error States

1. **Empty State**:
   - Message: "No data available. Please import an input bundle to get started."
   - Displayed in: `results-panel`.

2. **Loading State**:
   - Message: "Processing data... Please wait."
   - Displayed in: `status-strip`.

3. **Error State**:
   - Message: "An error occurred while processing the data. Please check your input and try again."
   - Displayed in: `status-strip`.

---

## Data Density

The application balances data density and readability by:

- Displaying a maximum of 10 highlight cards per page in the `results-panel`.
- Using pagination or infinite scrolling for large datasets.
- Including concise metadata fields in each highlight card.

---

## Visual Hierarchy

The visual hierarchy is established through:

1. **Typography**:
   - Larger font sizes for titles and headers.
   - Smaller font sizes for metadata and descriptions.

2. **Color Coding**:
   - Different colors for score badges to indicate highlight quality (e.g., green for high scores, yellow for medium, red for low).

3. **Spacing**:
   - Adequate spacing between elements to avoid clutter.

4. **Highlight Cards**:
   - Prominent display of titles and scores to draw attention to key information.

---

## Terminology

- **Highlight**: A notable moment in a game stream.
- **Score**: A numerical value representing the quality or impact of a highlight.
- **Category**: The type or genre of the highlight (e.g., "Epic Win," "Funny Moment").
- **Streamer**: The content creator of the game stream.
- **Game**: The video game being streamed.
- **Timestamp**: The time at which the highlight occurred in the stream.
- **Manual Tagging**: The process of adding user-defined highlights.

---

## Acceptance Criteria

1. The application must run locally using `python -m http.server`.
2. Users must be able to import industrial input bundles via `file-input` or `json-textarea`.
3. Imported data must be processed and displayed as scored highlights sorted in descending order.
4. Filter controls for streamer, game, category, and score must be functional.
5. Users must be able to manually tag highlights using the `manual-form`.
6. Export functionality must generate downloadable JSON or CSV files using `export-button`.
7. Highlight cards must display the following fields:
   - Title
   - Streamer
   - Game
   - Timestamp
   - Category
   - Score
   - Description

---

## Result DOM Contract

Each result card must adhere to the following DOM structure:

```html
<div class="highlight-card">
  <div class="highlight-title">[Title]</div>
  <div class="score-badge">[Score]</div>
  <div class="metadata-row">
    <span class="metadata-streamer">[Streamer]</span>
    <span class="metadata-game">[Game]</span>
    <span class="metadata-time">[Timestamp]</span>
    <span class="metadata-category">[Category]</span>
  </div>
  <div class="highlight-description">[Description]</div>
</div>
```

---

## UI Structure Classes

The following classes must be implemented in the UI:

### Required Classes
- `app-shell`
- `app-header`
- `workspace-grid`
- `intake-panel`
- `filters-panel`
- `results-panel`
- `manual-panel`
- `status-strip`
- `action-bar`

### Result Card Classes
- `highlight-card`
- `highlight-title`
- `score-badge`
- `metadata-row`
- `metadata-streamer`
- `metadata-game`
- `metadata-time`
- `metadata-category`
- `highlight-description`

---

## Conclusion

This UX and GUI design specification provides a comprehensive framework for the development of the Game Stream Highlight Identifier. By adhering to the defined information architecture, screen layouts, control groupings, and visual hierarchy, the application will meet the needs of its target users while maintaining clarity, efficiency, and scalability. The specified DOM contract and UI structure classes ensure consistency and alignment with the project’s goals and requirements.