// src/core/scoring.js

/**
 * Scores a record based on its properties and returns a new record with a numeric score.
 * @param {Object} record - The record to score.
 * @returns {Object} - A new record with the calculated score.
 */
export function scoreRecord(record) {
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordWeight = 0.2;
  const titleDescriptionBoost = 0.1;

  const intensityScore = record.intensity * intensityWeight;
  const chatRateScore = record.chatRate * chatRateWeight;
  const keywordScore = (record.keywords?.length || 0) * keywordWeight;

  const titleDescriptionScore =
    (record.title?.length > 0 || record.description?.length > 0) ? titleDescriptionBoost : 0;

  const totalScore = intensityScore + chatRateScore + keywordScore + titleDescriptionScore;

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