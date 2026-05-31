const LOCAL_STORAGE_KEY = 'cgnk.streamerHighlightFinder.records';

/**
 * Loads records from localStorage.
 * @returns {Array} Parsed records from localStorage or an empty array if none exist.
 */
export function loadFromLocalStorage() {
  const data = localStorage.getItem(LOCAL_STORAGE_KEY);
  return data ? JSON.parse(data) : [];
}

/**
 * Saves records to localStorage.
 * @param {Array} records - The records to save.
 */
export function saveToLocalStorage(records) {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(records));
}

/**
 * Clears all records from localStorage.
 */
export function clearRecords() {
  localStorage.removeItem(LOCAL_STORAGE_KEY);
}

// Aliases
export const loadRecords = loadFromLocalStorage;
export const saveRecords = saveToLocalStorage;