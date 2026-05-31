// src/core/scoring.js

/**
 * Calculates a score for a given record based on its properties.
 * @param {Object} record - The record to score.
 * @returns {Object} - A new record object with the calculated score.
 */
export function scoreRecord(record) {
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordsWeight = 0.2;
  const titleDescriptionBoost = 0.1;

  const intensityScore = record.intensity * intensityWeight;
  const chatRateScore = record.chatRate * chatRateWeight;
  const keywordsScore = (record.keywords?.length || 0) * keywordsWeight;

  const titleDescriptionScore =
    (record.title?.length > 0 || record.description?.length > 0) ? titleDescriptionBoost : 0;

  const totalScore = intensityScore + chatRateScore + keywordsScore + titleDescriptionScore;

  return {
    ...record,
    score: parseFloat(totalScore.toFixed(2)), // Ensure numeric score with two decimal places
  };
}

/**
 * Sorts an array of records by their score in descending order.
 * @param {Array<Object>} records - The array of records to sort.
 * @returns {Array<Object>} - The sorted array of records.
 */
export function sortRecords(records) {
  return records.sort((a, b) => b.score - a.score);
}