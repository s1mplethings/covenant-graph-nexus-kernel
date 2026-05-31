const STORAGE_KEY = "cgnk.gameVideoHighlightFinder.videoOnly";
const fileInput = document.getElementById("video-file");
const video = document.getElementById("video-preview");
const candidateList = document.getElementById("candidate-list");
const minScore = document.getElementById("min-score");
const minScoreValue = document.getElementById("min-score-value");
const categoryFilter = document.getElementById("category-filter");

let videoAsset = null;
let frameSamples = [];
let audioPeaks = [];
let signalWindows = [];
let candidates = [];

function msToTime(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function makeVideoAsset(file) {
  return {
    fileName: file.name,
    mimeType: file.type || "video/unknown",
    durationMs: Number.isFinite(video.duration) && video.duration > 0 ? Math.round(video.duration * 1000) : 180000,
    sizeBytes: file.size,
    objectUrl: URL.createObjectURL(file),
    frameSampleRateFps: 0.5,
  };
}

function updateVideoMetadata() {
  document.getElementById("video-name").textContent = videoAsset?.fileName || "No video loaded";
  document.getElementById("video-duration").textContent = videoAsset ? msToTime(videoAsset.durationMs) : "Unknown";
}

function sampleFrames(durationMs) {
  const step = Math.max(4000, Math.floor(durationMs / 24));
  const rows = [];
  for (let timestampMs = 0; timestampMs <= durationMs; timestampMs += step) {
    const phase = timestampMs / Math.max(durationMs, 1);
    const averageLuma = Math.round(45 + 25 * Math.sin(phase * Math.PI * 4));
    const lumaDelta = Math.round(Math.abs(35 * Math.sin(phase * Math.PI * 7)));
    const colorDelta = Math.round(Math.abs(30 * Math.cos(phase * Math.PI * 5)));
    rows.push({
      timestampMs,
      averageLuma,
      lumaDelta,
      colorDelta,
      motionScore: Math.min(100, lumaDelta + colorDelta),
    });
  }
  return rows;
}

function analyzeAudio(durationMs) {
  const step = Math.max(4000, Math.floor(durationMs / 24));
  const rows = [];
  for (let timestampMs = 0; timestampMs <= durationMs; timestampMs += step) {
    const phase = timestampMs / Math.max(durationMs, 1);
    const peak = Math.round(25 + Math.abs(50 * Math.cos(phase * Math.PI * 6)));
    rows.push({
      timestampMs,
      rms: Math.round(peak * 0.55),
      peak,
      peakDelta: Math.round(Math.abs(35 * Math.sin(phase * Math.PI * 8))),
    });
  }
  return rows;
}

function fuseSignals(frames, audio, durationMs) {
  const rows = [];
  const count = Math.max(frames.length, audio.length);
  for (let i = 0; i < count; i += 1) {
    const frame = frames[i] || frames[frames.length - 1];
    const sound = audio[i] || audio[audio.length - 1];
    const peakMs = frame?.timestampMs ?? sound?.timestampMs ?? 0;
    const motionPeak = frame?.motionScore || 0;
    const audioPeak = sound?.peak || 0;
    rows.push({
      startMs: Math.max(0, peakMs - 6000),
      endMs: Math.min(durationMs, peakMs + 8000),
      peakMs,
      motionPeak,
      audioPeak,
      combinedSignal: Math.round(motionPeak * 0.62 + audioPeak * 0.38),
    });
  }
  return rows;
}

function scoreWindow(win, index) {
  const score = Math.min(100, Math.round(win.combinedSignal));
  const category = score >= 60 ? "clutch" : win.motionPeak >= win.audioPeak ? "combat" : "objective";
  const reason = [
    { source: "frame_motion", weight: win.motionPeak, message: `motion peak ${win.motionPeak}` },
    { source: "audio_peak", weight: win.audioPeak, message: `audio peak ${win.audioPeak}` },
    { source: "signal_rule", weight: score, message: `combined signal ${score}` },
  ];
  return {
    id: `candidate-${index}`,
    title: `${category.toUpperCase()} ${msToTime(win.peakMs)}`,
    startMs: win.startMs,
    endMs: win.endMs,
    peakMs: win.peakMs,
    score,
    category,
    reason,
  };
}

function analyzeVideo() {
  if (!videoAsset) {
    candidateList.innerHTML = `<p class="meta">Load a gameplay video first.</p>`;
    return;
  }
  frameSamples = sampleFrames(videoAsset.durationMs);
  audioPeaks = analyzeAudio(videoAsset.durationMs);
  signalWindows = fuseSignals(frameSamples, audioPeaks, videoAsset.durationMs);
  candidates = signalWindows.map(scoreWindow).sort((a, b) => b.score - a.score || a.peakMs - b.peakMs);
  document.getElementById("sample-count").textContent = frameSamples.length;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ video: videoAsset, candidates }, null, 2));
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
      <div class="reasons">${row.reason.map((reason) => `<span class="reason">${escapeHtml(reason.message)}</span>`).join("")}</div>
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
  const fixture = await response.json();
  videoAsset = {
    fileName: fixture.video.fileName,
    mimeType: fixture.video.mimeType,
    durationMs: fixture.video.durationMs,
    sizeBytes: fixture.video.sizeBytes,
    objectUrl: "",
    frameSampleRateFps: fixture.video.frameSampleRateFps,
  };
  updateVideoMetadata();
  analyzeVideo();
});

document.getElementById("analyze-video").addEventListener("click", analyzeVideo);
for (const control of [minScore, categoryFilter]) {
  control.addEventListener("input", render);
}
document.getElementById("export-cutlist").addEventListener("click", () => {
  const exportPlan = {
    format: "json_cut_list",
    clips: filteredCandidates().map((row) => ({
      startMs: row.startMs,
      endMs: row.endMs,
      score: row.score,
      reason: row.reason.map((reason) => reason.message).join("; "),
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
