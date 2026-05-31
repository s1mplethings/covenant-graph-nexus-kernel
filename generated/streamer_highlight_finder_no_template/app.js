const SPEC = window.CGNK_PROJECT_SPEC;
const STORAGE_KEY = `cgnk.dynamic.${SPEC.project_type}.records`;
const jsonInput = document.getElementById("jsonInput");
const results = document.getElementById("results");
let records = loadRecords();
let ranked = [];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function loadRecords() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return Array.isArray(stored) ? stored : SPEC.sample_records;
  } catch {
    return SPEC.sample_records;
  }
}

function saveRecords() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records, null, 2));
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function scoreRecord(record) {
  const intensity = toNumber(record.intensity);
  const chatRate = Math.min(220, toNumber(record.chatRate));
  const keywords = Array.isArray(record.keywords) ? record.keywords.join(" ").toLowerCase() : String(record.keywords || "").toLowerCase();
  let score = intensity * 0.6 + chatRate * 0.25;
  for (const boost of SPEC.keyword_boosts || []) {
    if (keywords.includes(String(boost).toLowerCase())) score += 8;
  }
  return Math.max(0, Math.min(100, Math.round(score)));
}

function normalize(record, index) {
  return { id: record.id || `record-${index}-${Date.now()}`, ...record, score: scoreRecord(record) };
}

function analyze() {
  try {
    const parsed = JSON.parse(jsonInput.value || "[]");
    records = Array.isArray(parsed) ? parsed : [];
    saveRecords();
    ranked = records.map(normalize).sort((a, b) => b.score - a.score);
    render();
  } catch (error) {
    results.innerHTML = `<p class="meta">JSON parse error: ${escapeHtml(error.message)}</p>`;
  }
}

function applyFilters() {
  const minScore = toNumber(document.getElementById("minScore").value);
  return ranked.filter((record) => {
    if (record.score < minScore) return false;
    for (const control of document.querySelectorAll("[data-filter]")) {
      const field = control.dataset.filter;
      const expected = control.value.trim().toLowerCase();
      if (expected && !String(record[field] || "").toLowerCase().includes(expected)) return false;
    }
    return true;
  });
}

function render() {
  const rows = applyFilters();
  document.getElementById("totalCount").textContent = `${ranked.length} total`;
  document.getElementById("resultCount").textContent = `${rows.length} shown`;
  document.getElementById("topScore").textContent = `${rows[0]?.score || 0} top`;
  results.innerHTML = rows.map(renderCard).join("") || '<p class="meta">No matching records.</p>';
}

function renderCard(record) {
  const tags = Array.isArray(record.keywords) ? record.keywords.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("") : "";
  return `<article class="card">
    <h3>${escapeHtml(record.title || record.time || "Untitled moment")}</h3>
    <p class="meta">${escapeHtml(record.streamer || "Unknown")} · ${escapeHtml(record.game || "Unknown game")} · ${escapeHtml(record.time || "")} · Score ${record.score}</p>
    <p>${escapeHtml(record.description || "")}</p>
    <div class="tags">${tags}</div>
  </article>`;
}

document.getElementById("fileInput").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    jsonInput.value = String(reader.result || "[]");
    analyze();
  };
  reader.readAsText(file);
});

document.getElementById("loadSample").addEventListener("click", () => {
  records = SPEC.sample_records;
  jsonInput.value = JSON.stringify(records, null, 2);
  analyze();
});

document.getElementById("analyze").addEventListener("click", analyze);
document.querySelectorAll("[data-filter], #minScore").forEach((control) => control.addEventListener("input", render));

document.getElementById("manualForm").addEventListener("submit", (event) => {
  event.preventDefault();
  records.push({
    streamer: document.getElementById("manualStreamer").value.trim(),
    game: "Manual",
    time: document.getElementById("manualTime").value.trim(),
    title: document.getElementById("manualTitle").value.trim(),
    category: "manual",
    intensity: 80,
    chatRate: 80,
    keywords: ["manual", "marker"],
    description: "Manually added highlight marker."
  });
  jsonInput.value = JSON.stringify(records, null, 2);
  event.target.reset();
  analyze();
});

document.getElementById("exportResult").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(applyFilters(), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${SPEC.project_type}-clips.json`;
  link.click();
  URL.revokeObjectURL(url);
});

jsonInput.value = JSON.stringify(records, null, 2);
analyze();
