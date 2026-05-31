// src/core/importer.js

/**
 * Parses raw text input into an array of records.
 * @param {string} text - Raw text input containing JSON or newline-separated records.
 * @returns {Array<Object>} - Parsed records.
 */
export function parseRecordsFromText(text) {
  try {
    // Attempt to parse as JSON
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    // Fallback to newline-separated parsing
    return text
      .split("\n")
      .map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(record => record !== null);
  }
}

/**
 * Normalizes a record by ensuring all required fields are present and formatted correctly.
 * @param {Object} record - The raw record to normalize.
 * @param {number} index - The index of the record in the dataset.
 * @returns {Object} - Normalized record.
 */
export function normalizeRecord(record, index) {
  return {
    streamer: record.streamer || `Unknown Streamer ${index}`,
    game: record.game || "Unknown Game",
    timestamp: record.timestamp || new Date().toISOString(),
    time: record.time || "00:00:00",
    category: record.category || "Uncategorized",
    intensity: typeof record.intensity === "number" ? record.intensity : 0,
    chatRate: typeof record.chatRate === "number" ? record.chatRate : 0,
    keywords: Array.isArray(record.keywords) ? record.keywords : [],
    title: record.title || `Untitled Highlight ${index}`,
    description: record.description || "",
    score: typeof record.score === "number" ? record.score : 0
  };
}

/**
 * Imports data from an array or JSON text, normalizes each record, and returns an array of normalized records.
 * @param {string|Array<Object>} input - JSON text or array of raw records.
 * @returns {Array<Object>} - Array of normalized records.
 */
export function importData(input) {
  let rawRecords = [];
  if (typeof input === "string") {
    rawRecords = parseRecordsFromText(input);
  } else if (Array.isArray(input)) {
    rawRecords = input;
  } else {
    throw new Error("Invalid input format. Must be JSON text or an array of records.");
  }

  return rawRecords.map((record, index) => normalizeRecord(record, index));
}