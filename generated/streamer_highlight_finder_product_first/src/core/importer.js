// src/core/importer.js

/**
 * Parses raw text input into an array of records.
 * @param {string} text - The raw text input containing JSON data.
 * @returns {Array} - Parsed array of records.
 */
export function parseRecordsFromText(text) {
  try {
    const data = JSON.parse(text);
    if (Array.isArray(data)) {
      return data;
    } else {
      throw new Error("Input data is not an array.");
    }
  } catch (error) {
    console.error("Failed to parse text:", error);
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
 * Imports data from an array or JSON text, normalizes each record, and returns an array.
 * @param {string|Array} input - The input data as JSON text or an array of records.
 * @returns {Array} - Array of normalized records.
 */
export function importData(input) {
  let records = [];
  if (typeof input === "string") {
    records = parseRecordsFromText(input);
  } else if (Array.isArray(input)) {
    records = input;
  } else {
    console.error("Invalid input format. Must be JSON text or an array.");
    return [];
  }

  return records.map((record, index) => normalizeRecord(record, index));
}