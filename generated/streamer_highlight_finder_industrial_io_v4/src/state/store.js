// src/state/store.js

const STORAGE_KEY = 'cgnk.streamerHighlightFinder.records';

/**
 * Load records from localStorage.
 * @returns {Array} The parsed records array or an empty array if no data exists.
 */
export function loadFromLocalStorage() {
  const data = localStorage.getItem(STORAGE_KEY);
  return data ? JSON.parse(data) : [];
}

/**
 * Save records to localStorage.
 * @param {Array} records - The records array to save.
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

// Aliases for load and save functions
export const loadRecords = loadFromLocalStorage;
export const saveRecords = saveToLocalStorage;