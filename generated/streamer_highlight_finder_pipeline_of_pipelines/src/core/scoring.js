// src/core/scoring.js

/**
 * Calculates a score for a given record based on its properties.
 * @param {Object} record - The record to score.
 * @param {string} record.streamer - The streamer's name.
 * @param {string} record.game - The game being streamed.
 * @param {string} record.category - The category of the stream.
 * @param {number} record.intensity - The intensity of the moment.
 * @param {number} record.chatRate - The rate of chat activity.
 * @param {Array<string>} record.keywords - Keywords associated with the moment.
 * @param {string} record.title - The title of the stream.
 * @param {string} record.description - The description of the stream.
 * @returns {Object} - A new record object with a calculated numeric score.
 */
export function scoreRecord(record) {
  const intensityWeight = 0.4;
  const chatRateWeight = 0.3;
  const keywordBoost = 0.2;
  const titleDescriptionBoost = 0.1;

  const keywordScore = record.keywords.length * keywordBoost;
  const titleDescriptionScore =
    (record.title.length + record.description.length) * titleDescriptionBoost;

  const score =
    record.intensity * intensityWeight +
    record.chatRate * chatRateWeight +
    keywordScore +
    titleDescriptionScore;

  return {
    ...record,
    score: parseFloat(score.toFixed(2)), // Ensure score is a numeric value with two decimals
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