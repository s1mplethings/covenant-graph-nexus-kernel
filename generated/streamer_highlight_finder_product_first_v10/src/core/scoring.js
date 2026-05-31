// src/core/scoring.js

/**
 * Function to calculate and return a new record with a numeric score.
 * @param {Object} record - The input record containing fields for scoring.
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

  // Define scoring weights
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
  const titleDescriptionBoost =
    (title.length > 0 || description.length > 0 ? 1 : 0) *
    weights.titleDescriptionBoost;

  // Total score
  const totalScore =
    intensityScore + chatRateScore + keywordScore + titleDescriptionBoost;

  // Return a new record with the calculated score
  return {
    ...record,
    score: parseFloat(totalScore.toFixed(2)), // Ensure score is a number with 2 decimal places
  };
}

/**
 * Function to sort records by score in descending order.
 * @param {Array<Object>} records - Array of records to be sorted.
 * @returns {Array<Object>} - Sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}