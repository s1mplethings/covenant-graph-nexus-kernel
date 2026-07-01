# TEST_REPORT

## Smoke Command
```bash
D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .
```

- status: PASS
- returncode: 0
- duration_seconds: 0.648
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260620T114029Z\generated_project\local_media_operations_workspace`

## commands_run
- D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .

## results
- exit_code: 0
- status: PASS

## adapter_status
- adapter_status: local_tool_verified
- commercial_ready: False
- media_metadata_status: ffprobe_verified
- ffprobe_status: local_tool_verified
- ffmpeg_status: local_tool_verified
- capability_manifest: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260620T114029Z\generated_project\local_media_operations_workspace\capability_manifest.json`

## stdout tail
```text
{'status': 'degraded', 'mode': 'local_fixture_processing', 'capability_manifest': 'capability_manifest.json', 'selected_adapter': 'local_tool_verified', 'artifacts': ['stage_plan.json', 'media_manifest.json', 'audio_chunk_manifest.json', 'transcript_merged.json', 'segment_analysis.json', 'selected_segments.json', 'clip_manifest.json', 'export_results.json'], 'not_real_ai_model': True, 'not_delivery_evidence': True}

```

## stderr tail
```text

```
