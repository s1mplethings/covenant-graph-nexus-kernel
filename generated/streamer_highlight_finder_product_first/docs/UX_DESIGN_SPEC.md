# UX and GUI Design Specification

## Information Architecture
The application is structured into three primary sections:
1. **Dashboard**: Provides an overview of imported streams and filtering/sorting options.
2. **Highlight Editor**: Displays detected highlights in a timeline view and allows manual adjustments.
3. **Export Screen**: Enables exporting of highlight lists or clips with preview functionality.

### Navigation
- **Primary Navigation**: Tabs or buttons to switch between Dashboard, Highlight Editor, and Export Screen.
- **Secondary Navigation**: Contextual controls within each screen for specific tasks (e.g., filtering, manual marking, exporting).

---

## Primary Screen Layout
### Dashboard
- **Header**: Application title and navigation links.
- **Workspace Grid**:
  - **Intake Panel**: Import stream data (file input, textarea, import button).
  - **Filters Panel**: Filtering controls (streamer, game, category, score).
  - **Results Panel**: List of streams with detected highlights.

### Highlight Editor
- **Header**: Stream title and navigation links.
- **Workspace Grid**:
  - **Timeline View**: Visual representation of detected highlights.
  - **Manual Panel**: Tools for manual adjustments (trimming, re-scoring).
  - **Status Strip**: Summary of current highlight statistics.

### Export Screen
- **Header**: Export options and navigation links.
- **Workspace Grid**:
  - **Preview Highlights**: Display selected highlights for export.
  - **Action Bar**: Export controls (format selection, download button).

---

## Control Grouping
### Dashboard
- **Intake Panel**:
  - File input (`file-input`)
  - JSON textarea (`json-textarea`)
  - Import button (`import-button`)
- **Filters Panel**:
  - Streamer filter (`filterStreamer`)
  - Game filter (`filterGame`)
  - Category filter (`filterCategory`)
  - Score filter (`filterScore`)
- **Results Panel**:
  - Container for rendered records (`records-container`)

### Highlight Editor
- **Timeline View**:
  - Detected highlights displayed visually.
- **Manual Panel**:
  - Manual marker form (`manual-form`)
  - Controls for trimming and re-scoring.

### Export Screen
- **Preview Highlights**:
  - Container for previewing selected highlights.
- **Action Bar**:
  - Export button (`export-button`)

---

## Empty/Loading/Error States
### Empty State
- **Dashboard**: "No streams imported. Please import a stream to get started."
- **Highlight Editor**: "No highlights detected. Adjust settings or import a different stream."
- **Export Screen**: "No highlights selected for export."

### Loading State
- **Dashboard**: Spinner with "Importing stream data..."
- **Highlight Editor**: Spinner with "Processing highlights..."
- **Export Screen**: Spinner with "Preparing export..."

### Error State
- **Dashboard**: "Failed to import stream data. Please try again."
- **Highlight Editor**: "Error processing highlights. Check your data and settings."
- **Export Screen**: "Export failed. Please try again."

---

## Data Density
- **Dashboard**: Compact list view with key details (streamer, game, timestamp, score).
- **Highlight Editor**: Timeline view with adjustable zoom for detailed or overview perspectives.
- **Export Screen**: Preview highlights with thumbnails and metadata.

---

## Visual Hierarchy
1. **Primary Actions**: Import, filter, export buttons (high visibility, bold colors).
2. **Secondary Actions**: Manual adjustments, sorting controls (medium visibility, neutral colors).
3. **Informational Elements**: Highlight statistics, summaries (low visibility, subtle colors).

---

## Terminology
- **Stream**: A gaming video session imported into the tool.
- **Highlight**: A detected moment of high engagement within a stream.
- **Score**: A numeric value representing the engagement level of a highlight.
- **Export**: The process of saving highlights as files or lists.

---

## Acceptance Criteria
1. **Functionality**:
   - Application must run locally from `index.html` under `python -m http.server`.
   - Import stream data via file input or textarea and process it.
   - Assign numeric scores to imported records and sort them descending.
   - Provide visible filter controls and executable filtering logic.
   - Allow manual marking of highlights and append them to the dataset.
   - Export filtered results using Blob, URL.createObjectURL, and anchor download.
   - Persist working data locally with `localStorage` and reload it on page load.

2. **UI Structure**:
   - Use the following required classes:
     - `app-shell`
     - `app-header`
     - `workspace-grid`
     - `intake-panel`
     - `filters-panel`
     - `results-panel`
     - `manual-panel`
     - `status-strip`
     - `action-bar`
   - Ensure clear ownership of controls and progressive complexity.

3. **Performance**:
   - Handle streams up to 4 hours long without performance issues.
   - Complete key tasks (importing, editing, exporting) within 5 minutes on average.

4. **Accuracy**:
   - Highlight detection must achieve at least 85% accuracy.

5. **Testing**:
   - Unit tests for core functionalities.
   - Integration tests for seamless interaction between modules.
   - User testing for usability feedback.
   - Performance testing with large datasets.