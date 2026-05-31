# Game Video Highlight Finder: Corrected I/O and Agent Generation Pipeline

## 0. Correction

The product runtime input should be one required input:

```text
GameVideoFile
```

Event JSON, chat logs, telemetry, and manual marks are not part of the MVP input contract. They can be future sidecar inputs, but the generated project should first prove the direct path:

```text
video -> frame/audio signals -> highlight windows -> ranked highlights -> cut list
```

The agent generation pipeline is also not one flat line. It is a set of sub-pipelines that produce artifacts and converge at unified control.

---

## 1. Runtime Input

```ts
type GameVideoFile = {
  file: File;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
};
```

The browser derives metadata after loading the video:

```ts
type VideoMetadata = {
  durationMs: number;
  width: number;
  height: number;
  fpsEstimate?: number;
  objectUrl: string;
};
```

This is derived state, not user input.

---

## 2. Runtime Intermediate Objects

The intermediate chain should map directly from video analysis.

```ts
type FrameSample = {
  timestampMs: number;
  averageLuma: number;
  lumaDelta: number;
  colorDelta: number;
  motionScore: number;
};

type AudioPeak = {
  timestampMs: number;
  rms: number;
  peak: number;
  peakDelta: number;
};

type SignalWindow = {
  startMs: number;
  endMs: number;
  peakMs: number;
  motionPeak: number;
  audioPeak: number;
  combinedSignal: number;
};

type HighlightCandidate = {
  id: string;
  startMs: number;
  endMs: number;
  peakMs: number;
  score: number;
  reason: HighlightReason[];
  previewFrame?: string;
};

type HighlightReason = {
  source: "frame_motion" | "scene_change" | "audio_peak" | "signal_rule";
  weight: number;
  message: string;
};
```

Correct runtime pipeline:

```text
GameVideoFile
  -> VideoMetadata
  -> FrameSample[]
  -> AudioPeak[]
  -> SignalWindow[]
  -> HighlightCandidate[]
```

---

## 3. Runtime Output

```ts
type HighlightResult = {
  video: VideoMetadata;
  candidates: HighlightCandidate[];
  summary: HighlightSummary;
  exportPlan: ExportPlan;
  diagnostics: DetectionDiagnostic[];
};

type HighlightSummary = {
  durationMs: number;
  sampledFrames: number;
  audioWindows: number;
  candidateCount: number;
  topScore: number;
};

type ExportPlan = {
  format: "json_cut_list";
  clips: ExportClip[];
};

type ExportClip = {
  startMs: number;
  endMs: number;
  score: number;
  reason: string;
};

type DetectionDiagnostic = {
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
};
```

---

## 4. Agent Generation Inputs

This is the input to CGNK while generating the project, not the runtime app input.

```ts
type AgentGenerationInput = {
  userRequirement: string;
  moduleCatalog: ModuleContract[];
  artifactCatalog: ArtifactTypeSpec[];
  policies: PolicySpec[];
  localFirst: true;
  networkAllowed: false;
  providerAllowed: false;
};
```

---

## 5. Agent Generation Sub-Pipelines

Each line is a separate generation sub-pipeline. They should not be presented as one single line.

```text
customer_intake_pipeline
  input: userRequirement
  output: customerRequest

requirement_blueprint_pipeline
  input: customerRequest
  output: requirementBlueprint

io_contract_pipeline
  input: requirementBlueprint
  output: runtime I/O contract

local_librarian_pipeline
  input: moduleCatalog + artifactCatalog
  output: localLibraryIndex

route_planning_pipeline
  input: requirementBlueprint + localLibraryIndex
  output: routeQualityReport + selectedModules + edges

architecture_pipeline
  input: requirementBlueprint + ioContract + routePlan
  output: projectArchitecture

module_generation_pipelines
  input: projectArchitecture
  output: index.html, app.js, styles.css, tests, fixtures, docs

test_pipeline
  input: generatedProjectDir
  output: TestExecutionReport

effect_report_pipeline
  input: routePlan + generatedProject + testReport
  output: EffectReport

unified_control_pipeline
  input: all final artifacts
  output: runtimeResult
```

---

## 6. Agent Generation Outputs

```ts
type AgentGenerationOutput = {
  generatedProjectDir: string;
  generatedFiles: string[];
  routeQualityReport: RouteQualityReport;
  projectBlueprint: ProjectBlueprint;
  generationTrace: GenerationTrace;
  testGraph: TestGraph;
  testExecutionReport: TestExecutionReport;
  effectReport: EffectReport;
  runtimeResult: RuntimeExecutionResult;
};
```
