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
 * Normalizes a single record by extracting and preserving relevant fields.
 * @param {Object} record - The raw record to normalize.
 * @param {number} index - The index of the record in the dataset.
 * @returns {Object} - A normalized record.
 */
export function normalizeRecord(record, index) {
  const {
    sourceId,
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
    id: sourceId || `record-${index}`,
    sourceType: sourceType || null,
    viewerSpike: viewerSpike || null,
    clipSignal: clipSignal || null,
    confidence: confidence || null,
    moderationFlag: moderationFlag || null,
    streamer: streamer || "Unknown Streamer",
    game: game || "Unknown Game",
    category: category || "Uncategorized",
    timestamp: timestamp || time || null,
    title: title || "Untitled",
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
  } else if (typeof input === "object" && input !== null) {
    const records =
      input.records ||
      input.events ||
      input.highlights ||
      input.items ||
      (input.payload && input.payload.records);

    if (Array.isArray(records)) {
      return records.map((record, index) => normalizeRecord(record, index));
    } else {
      throw new Error("No valid records found in the input object");
    }
  } else if (typeof input === "string") {
    return parseRecordsFromText(input);
  } else {
    throw new Error("Unsupported input format");
  }
}