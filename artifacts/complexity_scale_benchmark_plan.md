# complexity-scale Benchmark Plan

Generated: 2026-06-18

## 1. Test Objective

Validate whether CGKN can generate a complete local project approaching 用户参考项目-level scale and complexity from a coarse goal.

This benchmark does not test:

- A single-page demo.
- A README-only artifact.
- A project manually completed by the agent.
- The agent's ability to hand-write missing target project code after CGKN fails.

The benchmark runner may collect evidence and score outputs. It must not implement the target local video workbench itself.

## 2. Input Prompt

Use this exact prompt as CGKN input:

```text
我要一个本地优先的视频素材处理工作台，用来导入视频，自动抽取音频，切分片段，生成转写，占位分析高价值片段，选择候选片段，渲染导出短片，并提供 GUI 和 CLI 两种使用方式。

要求：
1. 最多只能问我一轮澄清问题。
2. 必须先完成 product_brief、technical_plan、interaction_design、acceptance_matrix，再进入实现。
3. 必须有单一主流程 orchestrator，流程至少包括 ingest_video、extract_audio、chunk_audio、transcribe_audio、analyze_segments、select_segments、render_clips、export_results。
4. GUI 和 CLI 必须共享同一套 stages.py / orchestrator.py，不能各写一套逻辑。
5. 必须生成阶段 artifact，包括 stage_plan.json、media_manifest.json、audio_chunk_manifest.json、transcript_merged.json、segment_analysis.json、selected_segments.json、clip_manifest.json、export_results.json。
6. 每个 artifact 必须包含 stage、count、input_path、output_path、status、created_at，并且下游 artifact 能回指上游 artifact。
7. 必须支持无真实模型/无 ffmpeg 时的 honest degraded mode，不能假装真实处理成功。
8. 最终必须输出 README、TEST_REPORT、DELIVERY_NOTES、至少一张运行截图、final_project_bundle.zip、run_dir。
9. 最终回复必须说明 internal_acceptance、user_acceptance、known_gaps，以及哪些要求没有达成。
10. 不允许生成单文件 demo，不允许只做静态页面，不允许只有 README 没有可运行代码。
```

## 3. Acceptance Dimensions

The benchmark must check at least:

- `product_brief.md`
- `technical_plan.md`
- `interaction_design.md`
- `acceptance_matrix.md`
- `orchestrator.py`
- `stages.py`
- CLI entrypoint
- GUI entrypoint
- GUI/CLI shared use of `orchestrator.py` / `stages.py`
- Required stage artifacts
- Structured artifact fields
- Downstream artifact traceability to upstream artifact
- `README.md`
- `TEST_REPORT.md`
- `DELIVERY_NOTES.md`
- `final_project_bundle.zip`
- At least one running screenshot
- Real `run_dir`
- Honest degraded mode description
- Real test command/result evidence
- Fake PASS risk

## 4. Score Rules

Total score: 100.

- Product planning completeness: 15
- Technical architecture completeness: 15
- Single main pipeline: 15
- Artifact contract: 15
- GUI/CLI shared core: 10
- Runnability: 10
- Delivery completeness: 10
- Acceptance honesty: 10

Verdict:

- 85-100: PASS
- 65-84: PARTIAL
- 0-64: FAIL

Hard verdict caps:

- Missing `final_project_bundle.zip`: cannot be PASS.
- Missing `run_dir`: cannot be PASS.
- Missing `orchestrator.py` or `stages.py`: cannot be PASS.
- GUI/CLI not sharing core: cannot be PASS.
- Empty/shell artifacts: artifact contract fails.
- System claims PASS while key files are absent: mark `fake_pass_risk`.

## 5. Risk Register

- Degrades into a small demo.
- Produces a static GUI only.
- Produces artifact shells without real structure.
- Splits GUI and CLI into separate logic.
- Writes README/docs without runnable implementation.
- Omits screenshot.
- Omits zip.
- Omits real run evidence.
- Reports degraded mode dishonestly.
- Uses an acceptance gate that is too wide.

## 6. Execution Approach

1. Preserve current CGKN main generation logic before the first test.
2. Run a non-intrusive benchmark wrapper that calls the detected CGKN local pipeline entrypoint.
3. Save raw command logs, run summary, file inventory, generated project paths, and acceptance report under `artifacts/`.
4. Base every PASS/FAIL/PARTIAL conclusion on actual files and command logs.
5. Do not manually add or repair target project source files after CGKN generation.
