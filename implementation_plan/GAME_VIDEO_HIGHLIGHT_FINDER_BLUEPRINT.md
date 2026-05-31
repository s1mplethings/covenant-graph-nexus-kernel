# Game Video Highlight Finder Blueprint

## Product Goal

Build a local-first game video highlight finder. The user provides a gameplay video, optionally adds game telemetry or chat/event logs, and the app returns ranked highlight moments with timestamps, reasons, preview frames, and an exportable cut list.

The MVP must not pretend to do full computer vision if it does not. It should make its detection basis explicit: motion change, audio peaks, OCR/event-log hooks when available, chat spikes when available, manual marks, and rule-based scoring.

## Input Classes

```ts
type VideoInputBundle = {
  video: VideoAsset;
  optionalTelemetry?: TelemetryEvent[];
  optionalChat?: ChatEvent[];
  manualMarks?: ManualMark[];
  detectionProfile: DetectionProfile;
};

type VideoAsset = {
  fileName: string;
  mimeType: "video/mp4" | "video/webm" | "video/quicktime" | string;
  durationMs: number;
  sizeBytes: number;
  objectUrl: string;
  frameSampleRateFps: number;
};

type DetectionProfile = {
  gameTitle?: string;
  targetMomentTypes: Array<"kill" | "clutch" | "objective" | "boss" | "rank_up" | "funny" | "custom">;
  minScore: number;
  preRollMs: number;
  postRollMs: number;
  mergeWindowMs: number;
};

type FrameSample = {
  timestampMs: number;
  imageDataRef: string;
  averageLuma: number;
  colorDelta: number;
  motionScore: number;
};

type AudioSignal = {
  timestampMs: number;
  rms: number;
  peak: number;
  delta: number;
};

type TelemetryEvent = {
  timestampMs: number;
  eventType: string;
  actor?: string;
  target?: string;
  value?: number;
  raw?: unknown;
};

type ChatEvent = {
  timestampMs: number;
  author?: string;
  message: string;
  sentimentHint?: "hype" | "laugh" | "shock" | "neutral";
};

type ManualMark = {
  timestampMs: number;
  label: string;
  weight: number;
};
```

## Intermediate Classes

```ts
type SignalWindow = {
  startMs: number;
  endMs: number;
  motionPeak: number;
  audioPeak: number;
  chatSpike: number;
  telemetryWeight: number;
  manualWeight: number;
};

type HighlightCandidate = {
  id: string;
  startMs: number;
  endMs: number;
  peakMs: number;
  score: number;
  category: string;
  reasons: HighlightReason[];
  previewFrameRef?: string;
};

type HighlightReason = {
  source: "motion" | "audio" | "chat" | "telemetry" | "manual" | "rule";
  weight: number;
  message: string;
};
```

## Output Classes

```ts
type HighlightResult = {
  videoRef: string;
  candidates: HighlightCandidate[];
  rejectedCandidates: HighlightCandidate[];
  summary: HighlightSummary;
  exportPlan: ExportPlan;
  diagnostics: DetectionDiagnostic[];
};

type HighlightSummary = {
  durationMs: number;
  analyzedFrameCount: number;
  analyzedAudioWindowCount: number;
  candidateCount: number;
  topScore: number;
};

type ExportPlan = {
  format: "json_cut_list" | "edl" | "ffmpeg_commands" | "webcodecs_clips";
  clips: ExportClip[];
};

type ExportClip = {
  title: string;
  startMs: number;
  endMs: number;
  reason: string;
  ffmpegCommand?: string;
};

type DetectionDiagnostic = {
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
};
```

## Module Pipeline

1. `video_intake`: validate local video file and create a `VideoAsset`.
2. `frame_sampler`: sample frames through `<video>` + `<canvas>` and emit `FrameSample[]`.
3. `audio_analyzer`: inspect audio amplitude windows and emit `AudioSignal[]`.
4. `event_ingest`: normalize optional telemetry, chat logs, and manual marks.
5. `signal_fusion`: merge frame/audio/event signals into `SignalWindow[]`.
6. `highlight_scoring`: score windows into `HighlightCandidate[]`.
7. `candidate_merge`: merge nearby candidates and clamp pre-roll/post-roll.
8. `review_ui`: let the user inspect, accept, reject, relabel, and manually add moments.
9. `export_planner`: emit JSON cut list, EDL, ffmpeg commands, and optional clip export path.
10. `test_report`: output browser smoke, fixture checks, and effect report.

## Acceptance Tests

- Import a real local video file and show duration, file name, and preview playback.
- Sample frames without crashing and report analyzed frame count.
- Detect at least one highlight from a deterministic synthetic fixture with sharp visual/audio changes.
- Accept optional telemetry/chat/manual marks and incorporate them into scoring reasons.
- Sort candidates by score descending and support min-score/category filters.
- Export cut list JSON with `startMs`, `endMs`, `score`, `category`, and `reason`.
- Keep network/provider disabled unless explicit flags are passed.
