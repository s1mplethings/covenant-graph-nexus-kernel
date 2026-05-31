# Industrial Input/Output Specification for Game Stream Highlight Identifier

This document defines the industrial input/output (I/O) specification for the **Game Stream Highlight Identifier** project. It includes concrete input schemas, output schemas, field meanings, source categories, resource provenance labels, validation rules, edge cases, and the transformation process from input bundles to ranked highlights and exportable cut lists. The specification references the following files:

- **Input Bundle**: `data/industrial_input_bundle.json`
- **Expected Outputs**: `data/expected_outputs.json`
- **Test Script**: `tests/industrial_io_smoke_test.js`

---

## Input Schema

### Input Bundle Structure
The input bundle is a JSON file containing an array of records. Each record represents a potential highlight moment derived from various industrial sources. The schema is as follows:

#### Fields
| Field Name       | Type       | Description                                                                 |
|------------------|------------|-----------------------------------------------------------------------------|
| `sourceId`       | `string`   | Unique identifier for the data source.                                      |
| `streamer`       | `string`   | Name or ID of the streamer.                                                 |
| `game`           | `string`   | Name of the game being streamed.                                            |
| `category`       | `string`   | Category or type of highlight (e.g., "kill streak", "funny moment").        |
| `timestamp`      | `string`   | ISO 8601 timestamp of the event.                                            |
| `time`           | `number`   | Time offset in seconds from the start of the stream.                        |
| `title`          | `string`   | Title of the highlight or event.                                            |
| `description`    | `string`   | Detailed description of the highlight.                                      |
| `intensity`      | `number`   | Numeric score representing the intensity of the moment (e.g., 0-100).       |
| `chatRate`       | `number`   | Number of chat messages per second during the event.                        |
| `keywords`       | `array`    | Array of keywords associated with the highlight.                            |
| `viewerSpike`    | `boolean`  | Indicates whether there was a significant spike in viewer count.            |
| `clipSignal`     | `boolean`  | Indicates whether the moment was clipped by viewers.                        |

### Source Categories
The input bundle aggregates data from the following simulated industrial sources:

1. **Platform Event Logs**: Includes viewer count spikes, stream start/end events, and engagement metrics.
2. **Chat Analytics**: Sentiment analysis, keyword detection, and chat activity rates.
3. **Creator Manual Marks**: Highlights manually marked by the streamer or their team.
4. **Public Clip Metadata**: Metadata from publicly available clips, such as titles and timestamps.
5. **Moderation/Ops Annotations**: Notes from platform moderators or operational teams.

### Resource Provenance Labels
Each record includes provenance metadata to ensure traceability and trustworthiness:

| Provenance Field       | Description                                                                 |
|-------------------------|-----------------------------------------------------------------------------|
| `source_id`            | Unique identifier for the source.                                           |
| `source_type`          | Type of source (e.g., "platform_log", "chat_analytics").                    |
| `origin`               | Origin of the data (e.g., "Twitch", "YouTube").                             |
| `trust_level`          | Trustworthiness of the source (e.g., "high", "medium", "low").              |
| `license_or_access`    | Licensing or access information for the data.                               |
| `fields_provided`      | List of fields provided by the source.                                      |

---

## Output Schema

### Output Structure
The system generates two primary outputs:

1. **Ranked Highlights**: A JSON array of scored and sorted highlights.
2. **Export Cut List**: A downloadable JSON or CSV file containing filtered highlights.

#### Ranked Highlights
| Field Name       | Type       | Description                                                                 |
|------------------|------------|-----------------------------------------------------------------------------|
| `streamer`       | `string`   | Name or ID of the streamer.                                                 |
| `game`           | `string`   | Name of the game being streamed.                                            |
| `timestamp`      | `string`   | ISO 8601 timestamp of the event.                                            |
| `title`          | `string`   | Title of the highlight.                                                     |
| `description`    | `string`   | Detailed description of the highlight.                                      |
| `score`          | `number`   | Final computed score for the highlight.                                     |

#### Export Cut List
The export cut list includes the same fields as the ranked highlights but is formatted for external use (e.g., CSV).

---

## Field Meanings and Scoring Logic

### Scoring Algorithm
The scoring engine computes a numeric score for each record based on the following weighted factors:

- **Intensity**: Directly contributes to the score (weight: 40%).
- **Chat Rate**: Higher chat activity increases the score (weight: 30%).
- **Viewer Spike**: Adds a fixed bonus if true (weight: 20%).
- **Clip Signal**: Adds a fixed bonus if true (weight: 10%).

### Example Scoring Formula
```javascript
score = (intensity * 0.4) + (chatRate * 0.3) + (viewerSpike ? 10 : 0) + (clipSignal ? 5 : 0);
```

---

## Validation Rules

1. **Field Completeness**: All required fields must be present in each record.
2. **Data Types**: Fields must match the specified types (e.g., `intensity` must be a number).
3. **Timestamp Format**: Timestamps must follow the ISO 8601 standard.
4. **Minimum Record Count**: Input bundles must contain at least 20 records.
5. **Provenance Integrity**: Each record must include valid provenance metadata.

---

## Edge Cases

1. **Empty Input Bundle**: The system should display an error message and halt processing.
2. **Malformed Records**: Invalid records should be skipped, and a warning should be logged.
3. **Duplicate Records**: Records with identical `sourceId` and `timestamp` should be deduplicated.
4. **Extreme Values**: Handle edge values for numeric fields (e.g., `intensity` = 0 or 100).

---

## Transformation Process

1. **Import**: The user uploads the input bundle via file input or textarea.
2. **Validation**: The system validates the input bundle against the schema.
3. **Scoring**: Each record is scored using the scoring algorithm.
4. **Sorting**: Scored records are sorted in descending order of score.
5. **Filtering**: Users apply filters (e.g., by streamer, game, category, or score).
6. **Manual Adjustment**: Users can manually tag or adjust scores for highlights.
7. **Export**: The filtered highlights are exported as a JSON or CSV file.

---

## Test Coverage

### Smoke Test
The test script `tests/industrial_io_smoke_test.js` verifies the following:

1. **Input Validation**: Ensures the system correctly validates input bundles.
2. **Scoring Accuracy**: Confirms that scores are computed as expected.
3. **Sorting Logic**: Verifies that highlights are sorted in descending order of score.
4. **Filtering Functionality**: Tests the filtering logic for all supported fields.
5. **Export Integrity**: Ensures the exported file matches the filtered results.

---

## Example Input and Output

### Input Example (`data/industrial_input_bundle.json`)
```json
[
  {
    "sourceId": "log123",
    "streamer": "StreamerA",
    "game": "GameX",
    "category": "kill streak",
    "timestamp": "2023-10-01T12:34:56Z",
    "time": 1234,
    "title": "Epic Kill Streak",
    "description": "Achieved a 10-kill streak in under 2 minutes.",
    "intensity": 85,
    "chatRate": 15,
    "keywords": ["kill streak", "epic"],
    "viewerSpike": true,
    "clipSignal": false
  }
]
```

### Output Example (`data/expected_outputs.json`)
```json
[
  {
    "streamer": "StreamerA",
    "game": "GameX",
    "timestamp": "2023-10-01T12:34:56Z",
    "title": "Epic Kill Streak",
    "description": "Achieved a 10-kill streak in under 2 minutes.",
    "score": 58.5
  }
]
```

---

## Conclusion

This specification ensures a robust and scalable system for processing industrial input bundles, scoring highlights, and generating exportable cut lists. The system adheres to strict validation rules, handles edge cases gracefully, and provides a seamless user experience for streamers and content managers.