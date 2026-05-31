// src/core/scoring.js

/**
 * Function to calculate and assign a score to a record.
 * @param {Object} record - The input record containing fields like intensity, chatRate, keywords, category, title, and description.
 * @returns {Object} - A new record object with an added numeric score field.
 */
export function scoreRecord(record) {
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordBoost = 0.2;
  const categoryBoost = 0.05;
  const titleDescriptionBoost = 0.05;

  const keywordScore = record.keywords ? record.keywords.length * keywordBoost : 0;
  const categoryScore = record.category ? categoryBoost : 0;
  const titleDescriptionScore = (record.title ? 1 : 0) + (record.description ? 1 : 0) * titleDescriptionBoost;

  const score =
    record.intensity * intensityWeight +
    record.chatRate * chatRateWeight +
    keywordScore +
    categoryScore +
    titleDescriptionScore;

  return {
    ...record,
    score: parseFloat(score.toFixed(2)), // Ensure score is a numeric value with two decimal places
  };
}

/**
 * Function to sort an array of records by their score in descending order.
 * @param {Array} records - An array of records, each containing a numeric score field.
 * @returns {Array} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}