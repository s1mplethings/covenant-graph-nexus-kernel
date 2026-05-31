// src/core/scoring.js

/**
 * Calculates a score for a given record based on multiple factors.
 * Returns a new object with the original record fields and a calculated numeric score.
 * 
 * @param {Object} record - The input record containing fields like intensity, chatRate, keywords, etc.
 * @returns {Object} - A new record object with an added `score` field.
 */
export function scoreRecord(record) {
  const {
    intensity = 0,
    chatRate = 0,
    keywords = [],
    category = '',
    title = '',
    description = ''
  } = record;

  // Define weights for scoring
  const weights = {
    intensity: 0.4,
    chatRate: 0.3,
    keywords: 0.2,
    titleDescriptionBoost: 0.1
  };

  // Calculate individual components of the score
  const intensityScore = (intensity / 100) * weights.intensity;
  const chatRateScore = Math.min(chatRate / 100, 1) * weights.chatRate;
  const keywordScore = Math.min(keywords.length / 10, 1) * weights.keywords;
  const titleDescriptionBoost = (title.length > 0 || description.length > 0) ? weights.titleDescriptionBoost : 0;

  // Aggregate the total score
  const totalScore = intensityScore + chatRateScore + keywordScore + titleDescriptionBoost;

  // Return a new record with the calculated score
  return {
    ...record,
    score: parseFloat(totalScore.toFixed(3)) // Ensure score is a float with 3 decimal places
  };
}

/**
 * Sorts an array of records by their `score` field in descending order.
 * 
 * @param {Array<Object>} records - An array of records to be sorted.
 * @returns {Array<Object>} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}