// src/core/scoring.js

/**
 * Function to calculate the score for a given record.
 * @param {Object} record - The record to score.
 * @returns {Object} - A new record object with the calculated score.
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
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordBoost = 0.1;
  const categoryBoost = 0.1;
  const titleDescriptionBoost = 0.1;

  // Calculate keyword boost based on the number of keywords
  const keywordScore = keywords.length * keywordBoost;

  // Calculate category boost (example: specific categories might have higher weight)
  const categoryScore = category ? categoryBoost : 0;

  // Calculate title/description boost based on their presence
  const titleDescriptionScore =
    (title ? titleDescriptionBoost : 0) +
    (description ? titleDescriptionBoost : 0);

  // Final score calculation
  const score =
    intensity * intensityWeight +
    chatRate * chatRateWeight +
    keywordScore +
    categoryScore +
    titleDescriptionScore;

  // Return a new record with the calculated score
  return {
    ...record,
    score: parseFloat(score.toFixed(2)), // Ensure score is a numeric value with two decimal places
  };
}

/**
 * Function to sort records by score in descending order.
 * @param {Array<Object>} records - The array of records to sort.
 * @returns {Array<Object>} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}