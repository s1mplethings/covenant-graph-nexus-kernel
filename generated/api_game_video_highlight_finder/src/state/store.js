const LOCAL_STORAGE_KEY = 'cgnk.streamerHighlightFinder.records';

export function loadRecords() {
  return loadFromLocalStorage();
}

export function saveRecords(records) {
  return saveToLocalStorage(records);
}

export function clearRecords() {
  localStorage.removeItem(LOCAL_STORAGE_KEY);
}

export function loadFromLocalStorage() {
  const records = localStorage.getItem(LOCAL_STORAGE_KEY);
  return records ? JSON.parse(records) : [];
}

export function saveToLocalStorage(records) {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(records));
}