// src/core/scoring.js

/**
 * Scores a record based on its attributes and returns a new record with a numeric score.
 * @param {Object} record - The input record to score.
 * @returns {Object} - A new record with the calculated score.
 */
export function scoreRecord(record) {
  const {
    intensity = 0,
    chatRate = 0,
    keywords = [],
    category = "",
    title = "",
    description = "",
  } = record;

  // Define weights for scoring
  const weights = {
    intensity: 0.4,
    chatRate: 0.3,
    keywords: 0.2,
    titleDescriptionBoost: 0.1,
  };

  // Calculate individual components of the score
  const intensityScore = intensity * weights.intensity;
  const chatRateScore = chatRate * weights.chatRate;
  const keywordScore = keywords.length * weights.keywords;

  // Boost for title and description length
  const titleDescriptionBoost =
    (title.length + description.length) * weights.titleDescriptionBoost;

  // Total score
  const totalScore =
    intensityScore + chatRateScore + keywordScore + titleDescriptionBoost;

  // Return a new record with the score
  return {
    ...record,
    score: totalScore,
  };
}

/**
 * Sorts an array of records by their score in descending order.
 * @param {Array} records - The array of records to sort.
 * @returns {Array} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}