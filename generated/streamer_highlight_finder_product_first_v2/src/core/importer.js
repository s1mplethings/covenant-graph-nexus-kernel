// src/core/importer.js

/**
 * Parses raw text input into an array of records.
 * @param {string} text - Raw JSON text or array string.
 * @returns {Array} Parsed array of records.
 */
export function parseRecordsFromText(text) {
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.error("Failed to parse text input:", error);
    return [];
  }
}

/**
 * Normalizes a single record by ensuring all required fields are present and formatted.
 * @param {Object} record - The raw record object.
 * @param {number} index - The index of the record in the dataset.
 * @returns {Object} Normalized record.
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
 * @param {string|Array} input - Raw JSON text or array of records.
 * @returns {Array} Array of normalized records.
 */
export function importData(input) {
  const rawRecords = typeof input === "string" ? parseRecordsFromText(input) : input;
  if (!Array.isArray(rawRecords)) {
    console.error("Input data is not a valid array.");
    return [];
  }
  return rawRecords.map((record, index) => normalizeRecord(record, index));
}