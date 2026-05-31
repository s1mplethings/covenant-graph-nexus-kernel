const STORAGE_KEY = "cgnk.streamerHighlightFinder.events";
const input = document.getElementById("eventInput");
const results = document.getElementById("results");
const timeline = document.getElementById("timeline");
const minScore = document.getElementById("minScore");
const minScoreValue = document.getElementById("minScoreValue");
const filters = {
  streamer: document.getElementById("streamerFilter"),
  game: document.getElementById("gameFilter"),
  category: document.getElementById("categoryFilter"),
};

let events = [...window.CGNK_SAMPLE_EVENTS];
let highlights = [];

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function parseTime(value) {
  const parts = String(value || "0").split(":").map((part) => Number(part));
  if (parts.some(Number.isNaN)) return 0;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] || 0;
}

function scoreEvent(event) {
  const keywords = (event.keywords || []).join(" ").toLowerCase();
  let score = Number(event.intensity || 0) * 0.55 + Math.min(Number(event.chatRate || 0), 220) * 0.25;
  if (/clutch|ace|steal|comeback|1v|final|save|headshot|win/.test(keywords)) score += 18;
  if (/funny|rage|reaction|unexpected/.test(keywords)) score += 8;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function normalizeEvents(raw) {
  return raw.map((event, index) => ({
    id: event.id || `event-${index}`,
    streamer: event.streamer || "Unknown",
    game: event.game || "Unknown game",
    time: event.time || "00:00",
    seconds: parseTime(event.time),
    title: event.title || "Untitled moment",
    category: event.category || "general",
    intensity: Number(event.intensity || 50),
    chatRate: Number(event.chatRate || 0),
    keywords: Array.isArray(event.keywords) ? event.keywords : [],
    description: event.description || "",
  }));
}

function applyFilters(rows) {
  const streamer = filters.streamer.value.trim().toLowerCase();
  const game = filters.game.value.trim().toLowerCase();
  const category = filters.category.value;
  const threshold = Number(minScore.value);
  return rows.filter((row) => {
    if (row.score < threshold) return false;
    if (streamer && !row.streamer.toLowerCase().includes(streamer)) return false;
    if (game && !row.game.toLowerCase().includes(game)) return false;
    if (category && row.category !== category) return false;
    return true;
  });
}

function analyze() {
  try {
    const parsed = JSON.parse(input.value || "[]");
    events = normalizeEvents(Array.isArray(parsed) ? parsed : []);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(events, null, 2));
  } catch (error) {
    results.innerHTML = `<p class="meta">JSON parse failed: ${error.message}</p>`;
    return;
  }
  highlights = events
    .map((event) => ({ ...event, score: scoreEvent(event) }))
    .sort((a, b) => b.score - a.score || a.seconds - b.seconds);
  render();
}

function render() {
  minScoreValue.textContent = minScore.value;
  const rows = applyFilters(highlights);
  document.getElementById("eventCount").textContent = events.length;
  document.getElementById("highlightCount").textContent = rows.length;
  document.getElementById("topScore").textContent = rows[0]?.score || 0;
  results.innerHTML = rows.length ? rows.map(renderCard).join("") : `<p class="meta">No highlights match current filters.</p>`;
  renderTimeline(rows);
}

function renderCard(row) {
  const tags = row.keywords.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("");
  return `<article class="highlight-card">
    <div class="card-top">
      <div>
        <h3>${escapeHtml(row.title)}</h3>
        <p class="meta">${escapeHtml(row.streamer)} · ${escapeHtml(row.game)} · ${escapeHtml(row.time)} · ${escapeHtml(row.category)}</p>
      </div>
      <div class="score">${row.score}</div>
    </div>
    <p>${escapeHtml(row.description)}</p>
    <div class="tags">${tags}</div>
  </article>`;
}

function renderTimeline(rows) {
  const maxScore = Math.max(100, ...rows.map((row) => row.score));
  timeline.innerHTML = rows
    .slice()
    .sort((a, b) => a.seconds - b.seconds)
    .map((row) => `<div class="timeline-row">
      <span>${row.time}</span>
      <div class="bar" style="width:${Math.max(8, (row.score / maxScore) * 100)}%"></div>
      <strong>${row.score}</strong>
    </div>`)
    .join("");
}

document.getElementById("loadSample").addEventListener("click", () => {
  input.value = JSON.stringify(window.CGNK_SAMPLE_EVENTS, null, 2);
  localStorage.setItem(STORAGE_KEY, input.value);
  analyze();
});

document.getElementById("analyze").addEventListener("click", analyze);
document.getElementById("exportJson").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(applyFilters(highlights), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "streamer-highlights.json";
  link.click();
  URL.revokeObjectURL(url);
});

document.getElementById("manualForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = document.getElementById("manualTitle").value.trim();
  const time = document.getElementById("manualTime").value.trim();
  const streamer = document.getElementById("manualStreamer").value.trim();
  if (!title || !time || !streamer) return;
  events.push({
    streamer,
    game: "Manual",
    time,
    title,
    category: "manual",
    intensity: 80,
    chatRate: 80,
    keywords: ["manual"],
    description: "Manually added highlight marker.",
  });
  input.value = JSON.stringify(events, null, 2);
  event.target.reset();
  analyze();
});

for (const control of [minScore, filters.streamer, filters.game, filters.category]) {
  control.addEventListener("input", render);
}

input.value = localStorage.getItem(STORAGE_KEY) || JSON.stringify(window.CGNK_SAMPLE_EVENTS, null, 2);
analyze();
