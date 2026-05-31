// src/core/importer.js

/**
 * Parses records from a JSON text input.
 * @param {string} text - The JSON text to parse.
 * @returns {Array} - An array of normalized records.
 */
export function parseRecordsFromText(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error("Invalid JSON input");
  }

  if (Array.isArray(parsed)) {
    return parsed.map((record, index) => normalizeRecord(record, index));
  } else if (typeof parsed === "object" && parsed !== null) {
    return importData(parsed);
  } else {
    throw new Error("Unsupported JSON structure");
  }
}

/**
 * Normalizes a single record by extracting and standardizing key fields.
 * @param {Object} record - The raw record to normalize.
 * @param {number} index - The index of the record in the dataset.
 * @returns {Object} - The normalized record.
 */
export function normalizeRecord(record, index) {
  const {
    sourceId = `unknown-${index}`,
    sourceType,
    viewerSpike,
    clipSignal,
    confidence,
    moderationFlag,
    streamer,
    game,
    category,
    timestamp,
    time,
    title,
    description,
    intensity,
    chatRate,
    keywords,
  } = record;

  return {
    sourceId,
    sourceType,
    viewerSpike,
    clipSignal,
    confidence,
    moderationFlag,
    streamer: streamer || "unknown",
    game: game || "unknown",
    category: category || "unknown",
    timestamp: timestamp || time || null,
    title: title || "",
    description: description || "",
    intensity: intensity || 0,
    chatRate: chatRate || 0,
    keywords: Array.isArray(keywords) ? keywords : [],
  };
}

/**
 * Imports data from various input formats and extracts records.
 * @param {Array|Object|string} input - The input data to process.
 * @returns {Array} - An array of normalized records.
 */
export function importData(input) {
  if (Array.isArray(input)) {
    return input.map((record, index) => normalizeRecord(record, index));
  }

  if (typeof input === "string") {
    return parseRecordsFromText(input);
  }

  if (typeof input === "object" && input !== null) {
    const {
      records,
      events,
      highlights,
      items,
      payload,
    } = input;

    const extractedRecords =
      records ||
      events ||
      highlights ||
      items ||
      (payload && payload.records);

    if (Array.isArray(extractedRecords)) {
      return extractedRecords.map((record, index) =>
        normalizeRecord(record, index)
      );
    }
  }

  throw new Error("Unsupported input format");
}
