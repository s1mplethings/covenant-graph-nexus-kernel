// src/core/importer.js

/**
 * Parses records from raw text input (JSON or industrial input bundle).
 * @param {string} text - Raw text input.
 * @returns {Array} - Parsed records.
 */
export function parseRecordsFromText(text) {
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed;
    }
    return [];
  } catch (error) {
    console.error("Failed to parse text:", error);
    return [];
  }
}

/**
 * Normalizes a single record by extracting relevant fields and adding defaults.
 * @param {Object} record - Raw record object.
 * @param {number} index - Index of the record in the dataset.
 * @returns {Object} - Normalized record.
 */
export function normalizeRecord(record, index) {
  return {
    sourceId: record.sourceId || `source-${index}`,
    sourceType: record.sourceType || "unknown",
    viewerSpike: record.viewerSpike || 0,
    clipSignal: record.clipSignal || 0,
    confidence: record.confidence || 0,
    moderationFlag: record.moderationFlag || false,
    streamer: record.streamer || "unknown",
    game: record.game || "unknown",
    category: record.category || "general",
    timestamp: record.timestamp || new Date().toISOString(),
    time: record.time || 0,
    title: record.title || "Untitled",
    description: record.description || "",
    intensity: record.intensity || 0,
    chatRate: record.chatRate || 0,
    keywords: record.keywords || [],
  };
}

/**
 * Imports data from various input formats (array, JSON text, or industrial input bundle object).
 * @param {Array|Object|string} input - Input data.
 * @returns {Array} - Normalized records.
 */
export function importData(input) {
  let records = [];

  if (Array.isArray(input)) {
    records = input;
  } else if (typeof input === "string") {
    records = parseRecordsFromText(input);
  } else if (typeof input === "object" && input !== null) {
    const possibleSources = [
      input.records,
      input.events,
      input.highlights,
      input.items,
      input.payload?.records,
    ];
    for (const source of possibleSources) {
      if (Array.isArray(source)) {
        records = source;
        break;
      }
    }
  }

  return records.map((record, index) => normalizeRecord(record, index));
}