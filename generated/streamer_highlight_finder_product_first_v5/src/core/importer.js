// src/core/importer.js

/**
 * Parses raw text input into an array of records.
 * @param {string} text - The raw JSON text or array string.
 * @returns {Array<Object>} - Parsed array of records.
 */
export function parseRecordsFromText(text) {
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed;
    } else {
      throw new Error("Input must be a JSON array.");
    }
  } catch (error) {
    console.error("Failed to parse input text:", error);
    return [];
  }
}

/**
 * Normalizes a single record by ensuring all required fields are present and formatted.
 * @param {Object} record - The raw record object.
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
    score: typeof record.score === "number" ? record.score : 0,
  };
}

/**
 * Imports data from raw input, normalizes each record, and returns an array of processed records.
 * @param {string|Array<Object>} input - JSON text or an array of raw records.
 * @returns {Array<Object>} - Array of normalized records.
 */
export function importData(input) {
  let rawRecords = [];
  if (typeof input === "string") {
    rawRecords = parseRecordsFromText(input);
  } else if (Array.isArray(input)) {
    rawRecords = input;
  } else {
    console.error("Invalid input type. Must be a JSON string or an array.");
    return [];
  }

  return rawRecords.map((record, index) => normalizeRecord(record, index));
}