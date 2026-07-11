# TEST_REPORT

## Smoke Command
```bash
D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .
```

- status: PASS
- returncode: 0
- duration_seconds: 0.279
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260620T082031Z\generated_project\local_media_operations_workspace`

## commands_run
- D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .

## results
- exit_code: 0
- status: PASS

## stdout tail
```text
{'status': 'degraded', 'mode': 'local_fixture_processing', 'artifacts': ['stage_plan.json', 'media_manifest.json', 'audio_chunk_manifest.json', 'transcript_merged.json', 'segment_analysis.json', 'selected_segments.json', 'clip_manifest.json', 'export_results.json'], 'not_real_ai_model': True, 'not_delivery_evidence': True}

```

## stderr tail
```text

```
