// src/core/importer.js

/**
 * Parses records from a JSON text input.
 * @param {string} text - The JSON text input.
 * @returns {Array} - An array of normalized records.
 */
export function parseRecordsFromText(text) {
  try {
    const parsed = JSON.parse(text);

    if (Array.isArray(parsed)) {
      return parsed.map((record, index) => normalizeRecord(record, index));
    }

    if (typeof parsed === 'object' && parsed !== null) {
      const records =
        parsed.records ||
        parsed.events ||
        parsed.highlights ||
        parsed.items ||
        (parsed.payload && parsed.payload.records);

      if (Array.isArray(records)) {
        return records.map((record, index) => normalizeRecord(record, index));
      }

      return importData(parsed);
    }

    throw new Error('Invalid JSON structure.');
  } catch (error) {
    console.error('Error parsing JSON:', error);
    return [];
  }
}

/**
 * Normalizes a single record by extracting and preserving relevant fields.
 * @param {Object} record - The raw record object.
 * @param {number} index - The index of the record in the dataset.
 * @returns {Object} - A normalized record object.
 */
export function normalizeRecord(record, index) {
  return {
    id: record.id || `record-${index}`,
    streamer: record.streamer || record.creator || null,
    game: record.game || record.category || null,
    timestamp: record.timestamp || record.time || null,
    time: record.time || null,
    category: record.category || null,
    intensity: record.intensity || null,
    chatRate: record.chatRate || null,
    keywords: record.keywords || [],
    title: record.title || null,
    description: record.description || null,
    sourceId: record.sourceId || null,
    sourceType: record.sourceType || null,
    viewerSpike: record.viewerSpike || null,
    clipSignal: record.clipSignal || null,
    confidence: record.confidence || null,
    moderationFlag: record.moderationFlag || null,
  };
}

/**
 * Imports data from various input formats (array, JSON text, or industrial input bundle object).
 * @param {Array|Object|string} input - The input data.
 * @returns {Array} - An array of normalized records.
 */
export function importData(input) {
  if (Array.isArray(input)) {
    return input.map((record, index) => normalizeRecord(record, index));
  }

  if (typeof input === 'string') {
    return parseRecordsFromText(input);
  }

  if (typeof input === 'object' && input !== null) {
    const records =
      input.records ||
      input.events ||
      input.highlights ||
      input.items ||
      (input.payload && input.payload.records);

    if (Array.isArray(records)) {
      return records.map((record, index) => normalizeRecord(record, index));
    }

    throw new Error('Invalid object structure for industrial input.');
  }

  throw new Error('Unsupported input format.');
}