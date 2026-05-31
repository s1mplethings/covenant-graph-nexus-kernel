const STORAGE_KEY = "cgnk.gameVideoHighlightFinder.state";
const fileInput = document.getElementById("video-file");
const video = document.getElementById("video-preview");
const eventJson = document.getElementById("event-json");
const candidateList = document.getElementById("candidate-list");
const minScore = document.getElementById("min-score");
const minScoreValue = document.getElementById("min-score-value");
const categoryFilter = document.getElementById("category-filter");

let videoAsset = null;
let manualMarks = [];
let candidates = [];
let loadedFixture = null;

function msToTime(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function timeToMs(value) {
  const parts = String(value || "0").split(":").map(Number);
  if (parts.some(Number.isNaN)) return 0;
  if (parts.length === 3) return ((parts[0] * 3600) + (parts[1] * 60) + parts[2]) * 1000;
  if (parts.length === 2) return ((parts[0] * 60) + parts[1]) * 1000;
  return parts[0] * 1000;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function parseEvents() {
  try {
    const parsed = JSON.parse(eventJson.value || "[]");
    if (Array.isArray(parsed)) return parsed;
    return parsed.records || parsed.events || parsed.items || [];
  } catch {
    return [];
  }
}

function makeVideoAsset(file) {
  if (!file) return null;
  return {
    fileName: file.name,
    mimeType: file.type || "video/unknown",
    durationMs: Number.isFinite(video.duration) ? Math.round(video.duration * 1000) : 180000,
    sizeBytes: file.size,
    objectUrl: URL.createObjectURL(file),
    frameSampleRateFps: 0.5,
  };
}

function updateVideoMetadata() {
  document.getElementById("video-name").textContent = videoAsset?.fileName || "No video loaded";
  document.getElementById("video-duration").textContent = videoAsset ? msToTime(videoAsset.durationMs) : "Unknown";
}

function syntheticSignals(durationMs, events) {
  const windows = [];
  const step = Math.max(5000, Math.floor(durationMs / 20));
  for (let t = 0; t < durationMs; t += step) {
    const nearbyEvents = events.filter((event) => Math.abs(Number(event.timestampMs || 0) - t) < step);
    const eventBoost = nearbyEvents.reduce((sum, event) => sum + Number(event.value || 20), 0);
    const manualBoost = manualMarks.filter((mark) => Math.abs(mark.timestampMs - t) < step).reduce((sum, mark) => sum + mark.weight, 0);
    const motionPeak = Math.round(35 + 35 * Math.abs(Math.sin((t + durationMs) / 17000)));
    const audioPeak = Math.round(25 + 35 * Math.abs(Math.cos((t + durationMs) / 13000)));
    windows.push({
      startMs: Math.max(0, t - 4000),
      endMs: Math.min(durationMs, t + 7000),
      peakMs: t,
      motionPeak,
      audioPeak,
      telemetryWeight: eventBoost,
      manualWeight: manualBoost,
      eventTypes: nearbyEvents.map((event) => String(event.eventType || event.category || "").toLowerCase()),
    });
  }
  return windows;
}

function scoreWindow(win, index) {
  const score = Math.min(100, Math.round(win.motionPeak * 0.42 + win.audioPeak * 0.28 + win.telemetryWeight * 0.18 + win.manualWeight * 0.5));
  const category = win.manualWeight ? "manual" : win.eventTypes.includes("clutch") ? "clutch" : win.telemetryWeight > 25 ? "objective" : score > 78 ? "clutch" : "combat";
  const reasons = [
    { source: "motion", weight: win.motionPeak, message: `motion ${win.motionPeak}` },
    { source: "audio", weight: win.audioPeak, message: `audio ${win.audioPeak}` },
  ];
  if (win.telemetryWeight) reasons.push({ source: "telemetry", weight: win.telemetryWeight, message: "event spike" });
  if (win.manualWeight) reasons.push({ source: "manual", weight: win.manualWeight, message: "manual mark" });
  return {
    id: `candidate-${index}`,
    title: `${category.toUpperCase()} ${msToTime(win.peakMs)}`,
    startMs: win.startMs,
    endMs: win.endMs,
    peakMs: win.peakMs,
    score,
    category,
    reasons,
  };
}

function analyzeVideo() {
  const events = parseEvents();
  const durationMs = videoAsset?.durationMs || loadedFixture?.durationMs || 180000;
  const windows = syntheticSignals(durationMs, events);
  candidates = windows.map(scoreWindow).sort((a, b) => b.score - a.score || a.peakMs - b.peakMs);
  document.getElementById("sample-count").textContent = windows.length;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ videoAsset, manualMarks, candidates }, null, 2));
  render();
}

function filteredCandidates() {
  const threshold = Number(minScore.value);
  const category = categoryFilter.value;
  return candidates.filter((candidate) => candidate.score >= threshold && (!category || candidate.category === category));
}

function render() {
  minScoreValue.textContent = minScore.value;
  const rows = filteredCandidates();
  document.getElementById("candidate-count").textContent = rows.length;
  document.getElementById("top-score").textContent = rows[0]?.score || 0;
  document.getElementById("accepted-count").textContent = rows.length;
  candidateList.innerHTML = rows.length ? rows.map((row) => `
    <article class="candidate">
      <div class="candidate-top">
        <div>
          <h3>${escapeHtml(row.title)}</h3>
          <p class="meta">${msToTime(row.startMs)} - ${msToTime(row.endMs)} · ${escapeHtml(row.category)}</p>
        </div>
        <div class="score">${row.score}</div>
      </div>
      <div class="reasons">${row.reasons.map((reason) => `<span class="reason">${escapeHtml(reason.message)}</span>`).join("")}</div>
    </article>
  `).join("") : `<p class="meta">No candidates match current filters.</p>`;
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  videoAsset = makeVideoAsset(file);
  video.src = videoAsset.objectUrl;
  video.addEventListener("loadedmetadata", () => {
    if (videoAsset) videoAsset.durationMs = Math.round(video.duration * 1000) || videoAsset.durationMs;
    updateVideoMetadata();
  }, { once: true });
  updateVideoMetadata();
});

document.getElementById("load-synthetic").addEventListener("click", async () => {
  const response = await fetch("data/industrial_input_bundle.json");
  loadedFixture = await response.json();
  eventJson.value = JSON.stringify(loadedFixture.records, null, 2);
  videoAsset = {
    fileName: "synthetic-gameplay-fixture.webm",
    mimeType: "video/webm",
    durationMs: loadedFixture.durationMs,
    sizeBytes: 0,
    objectUrl: "",
    frameSampleRateFps: 0.5,
  };
  updateVideoMetadata();
  analyzeVideo();
});

document.getElementById("analyze-video").addEventListener("click", analyzeVideo);
document.getElementById("manual-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const timestampMs = timeToMs(document.getElementById("manual-time").value);
  const label = document.getElementById("manual-label").value.trim();
  if (!label) return;
  manualMarks.push({ timestampMs, label, weight: 60 });
  event.target.reset();
  analyzeVideo();
});
for (const control of [minScore, categoryFilter]) {
  control.addEventListener("input", render);
}
document.getElementById("export-cutlist").addEventListener("click", () => {
  const exportPlan = {
    format: "json_cut_list",
    clips: filteredCandidates().map((row) => ({
      title: row.title,
      startMs: row.startMs,
      endMs: row.endMs,
      reason: row.reasons.map((reason) => reason.message).join("; "),
    })),
  };
  const blob = new Blob([JSON.stringify(exportPlan, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "game-highlight-cut-list.json";
  link.click();
  URL.revokeObjectURL(url);
});

render();
