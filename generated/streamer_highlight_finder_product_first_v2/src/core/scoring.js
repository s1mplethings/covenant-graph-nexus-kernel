// src/core/scoring.js

/**
 * Calculates a score for a record based on various attributes and returns a new record with the score.
 * @param {Object} record - The input record containing attributes like intensity, chatRate, keywords, etc.
 * @returns {Object} - A new record with the calculated score added.
 */
export function scoreRecord(record) {
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordBoost = 0.2;
  const categoryBoost = 0.05;
  const titleDescriptionBoost = 0.05;

  const keywordScore = record.keywords ? record.keywords.length * keywordBoost : 0;
  const categoryScore = record.category ? categoryBoost : 0;
  const titleDescriptionScore = (record.title?.length || 0 + record.description?.length || 0) * titleDescriptionBoost;

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
 * Sorts an array of records by their score in descending order.
 * @param {Array<Object>} records - The array of records to be sorted.
 * @returns {Array<Object>} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}