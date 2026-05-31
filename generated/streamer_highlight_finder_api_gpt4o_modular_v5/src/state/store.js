// src/state/store.js

const LOCAL_STORAGE_KEY = 'cgnk.streamerHighlightFinder.records';

/**
 * Load records from localStorage.
 * @returns {Array} The parsed records array or an empty array if no data exists.
 */
export function loadFromLocalStorage() {
  const data = localStorage.getItem(LOCAL_STORAGE_KEY);
  return data ? JSON.parse(data) : [];
}

/**
 * Save records to localStorage.
 * @param {Array} records - The records array to save.
 */
export function saveToLocalStorage(records) {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(records));
}

/**
 * Clear all records from localStorage.
 */
export function clearRecords() {
  localStorage.removeItem(LOCAL_STORAGE_KEY);
}

// Alias loadFromLocalStorage to loadRecords
export const loadRecords = loadFromLocalStorage;

// Alias saveToLocalStorage to saveRecords
export const saveRecords = saveToLocalStorage;