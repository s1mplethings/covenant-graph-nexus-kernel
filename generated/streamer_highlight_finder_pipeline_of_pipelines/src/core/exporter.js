// src/core/exporter.js

export function downloadJson(filename, records) {
  const jsonString = JSON.stringify(records, null, 2);
  const blob = new Blob([jsonString], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  URL.revokeObjectURL(url);
}

export function exportData(records, filename = 'highlight-clips.json') {
  downloadJson(filename, records);
}