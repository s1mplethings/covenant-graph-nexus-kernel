// src/state/store.js

const STORAGE_KEY = 'cgnk.streamerHighlightFinder.records';

/**
 * Load records from localStorage.
 * @returns {Array} Parsed records or an empty array if no data exists.
 */
export function loadFromLocalStorage() {
  const data = localStorage.getItem(STORAGE_KEY);
  return data ? JSON.parse(data) : [];
}

/**
 * Save records to localStorage.
 * @param {Array} records - The records to save.
 */
export function saveToLocalStorage(records) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
}

/**
 * Clear all records from localStorage.
 */
export function clearRecords() {
  localStorage.removeItem(STORAGE_KEY);
}

// Alias functions for external usage
export const loadRecords = loadFromLocalStorage;
export const saveRecords = saveToLocalStorage;