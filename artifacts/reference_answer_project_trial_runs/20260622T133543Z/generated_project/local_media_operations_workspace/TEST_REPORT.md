# TEST_REPORT

## Smoke Command
```bash
D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .
```

- status: PASS
- returncode: 0
- duration_seconds: 0.888
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260622T133543Z\generated_project\local_media_operations_workspace`

## commands_run
- D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .

## results
- exit_code: 0
- status: PASS

## adapter_status
- adapter_status: local_tool_verified
- commercial_ready: False
- media_metadata_status: ffprobe_verified
- user_media_input_status: not_configured
- user_media_input_path: ``
- user_media_input_size: 
- user_media_input_sha256: 
- user_media_metadata_status: 
- user_media_adapter_status: 
- user_media_manifest: ``
- media_decode_status: not_attempted
- media_decode_tool: none
- media_decode_command: `[]`
- media_decode_returncode: None
- media_decode_timed_out: False
- media_decode_artifact: ``
- media_decode_output: ``
- media_decode_size: 0
- media_decode_sha256: 
- transcription_status: placeholder_transcription
- transcription_tool: none
- transcription_not_production_asr: False
- transcription_output_artifact: `transcription_adapter_result.json`
- ffprobe_status: local_tool_verified
- ffmpeg_status: local_tool_verified
- capability_manifest: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260622T133543Z\generated_project\local_media_operations_workspace\capability_manifest.json`

## stdout tail
```text
{'status': 'degraded', 'mode': 'local_fixture_processing', 'capability_manifest': 'capability_manifest.json', 'media_manifest': '', 'user_media_contract': {}, 'selected_adapter': 'local_tool_verified', 'artifacts': ['stage_plan.json', 'media_manifest.json', 'audio_chunk_manifest.json', 'transcript_merged.json', 'segment_analysis.json', 'selected_segments.json', 'clip_manifest.json', 'export_results.json'], 'not_real_ai_model': True, 'not_delivery_evidence': True}

```

## stderr tail
```text

```
