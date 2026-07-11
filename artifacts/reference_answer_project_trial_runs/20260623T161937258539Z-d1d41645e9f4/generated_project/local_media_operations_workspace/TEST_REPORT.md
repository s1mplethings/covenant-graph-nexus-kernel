# TEST_REPORT

## Smoke Command
```bash
D:\anaconda\python.exe cli.py --input fixtures/sample_audio.wav --output-dir .
```

- status: PASS
- returncode: 0
- duration_seconds: 1.584
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T161937258539Z-d1d41645e9f4\generated_project\local_media_operations_workspace`

## commands_run
- D:\anaconda\python.exe cli.py --input fixtures/sample_audio.wav --output-dir .

## results
- exit_code: 0
- status: PASS

## adapter_status
- adapter_status: local_tool_verified
- commercial_ready: False
- media_metadata_status: ffprobe_verified
- user_media_input_status: verified
- user_media_input_path: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T161937258539Z-d1d41645e9f4\generated_project\local_media_operations_workspace\fixtures\sample_audio.wav`
- user_media_input_size: 4044
- user_media_input_sha256: e14028da8a23188880c3539c39acdd26054ff7d5510647a8a6c286dd92884bde
- user_media_metadata_status: ffprobe_verified
- user_media_adapter_status: ffprobe_verified
- user_media_manifest: `media_manifest.json`
- media_decode_status: verified
- media_decode_tool: ffmpeg
- media_decode_command: `['C:\\Program Files\\ffmpeg\\bin\\ffmpeg.EXE', '-y', '-v', 'error', '-i', 'D:\\CGKN\\artifacts\\reference_answer_project_trial_runs\\20260623T161937258539Z-d1d41645e9f4\\generated_project\\local_media_operations_workspace\\fixtures\\sample_audio.wav', '-t', '0.20', '-ac', '1', '-ar', '8000', 'media_decode_output.wav']`
- media_decode_returncode: 0
- media_decode_timed_out: False
- media_decode_artifact: `media_decode_artifact.json`
- media_decode_output: `media_decode_output.wav`
- media_decode_size: 3278
- media_decode_sha256: d27bf387026c6fdbbc6b38959a718bb7d12e7264116a6722e9e029b3cc489938
- asr_status: placeholder_transcription
- asr_adapter_kind: none
- asr_evidence_tier: placeholder
- asr_command: `None`
- asr_returncode: None
- asr_timed_out: False
- asr_schema_valid: False
- asr_output_artifact: `None`
- asr_quality_report: `asr_multi_sample_report.json`
- asr_quality_status: not_ready
- asr_quality_adapter_kind: none
- asr_quality_evidence_tier: none
- asr_quality_sample_count: 0
- asr_quality_successful_samples: 0
- asr_quality_failed_samples: 0
- asr_quality_timeout_samples: 0
- asr_quality_invalid_output_samples: 0
- asr_quality_success_rate: 0.0
- asr_quality_non_empty_text_rate: 0.0
- asr_quality_non_empty_segments_rate: 0.0
- asr_production_candidate: False
- asr_production_verified: False
- asr_production_readiness_blockers: ['no_asr_configured: CGKN_REAL_ASR_CMD is not configured.']
- asr_production_asr: False
- asr_degraded: True
- commercial_promotion_decision: COMMERCIAL_BETA
- commercial_readiness_level: COMMERCIAL_BETA
- commercial_promotion_report: `production_asr_verification_report.json`
- commercial_promotion_blockers: ['fixture_or_non_real_asr_adapter', 'asr_evidence_tier_not_candidate:none', 'asr_quality_not_production_candidate:not_ready', 'sample_count_below_promotion_threshold', 'success_rate_below_promotion_threshold', 'missing_reference_transcripts', 'token_error_rate_unavailable', 'character_error_rate_unavailable', 'asr_path_degraded']
- transcription_status: placeholder_transcription
- transcription_tool: none
- transcription_not_production_asr: False
- transcription_output_artifact: `transcription_adapter_result.json`
- ffprobe_status: local_tool_verified
- ffmpeg_status: local_tool_verified
- capability_manifest: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T161937258539Z-d1d41645e9f4\generated_project\local_media_operations_workspace\capability_manifest.json`

## stdout tail
```text
{'status': 'degraded', 'mode': 'local_user_media_contract', 'capability_manifest': 'capability_manifest.json', 'media_manifest': 'media_manifest.json', 'user_media_contract': {'status': 'PASS', 'media_manifest': 'media_manifest.json', 'inspect_artifact': 'user_media_inspect.json', 'smoke_log': 'user_media_smoke_log.json', 'fixture_path': 'user_media_fixture.json', 'metadata_status': 'ffprobe_verified', 'adapter_status': 'ffprobe_verified', 'sha256': 'e14028da8a23188880c3539c39acdd26054ff7d5510647a8a6c286dd92884bde', 'size': 4044, 'blockers': []}, 'selected_adapter': 'local_tool_verified', 'artifacts': ['stage_plan.json', 'media_manifest.json', 'audio_chunk_manifest.json', 'transcript_merged.json', 'segment_analysis.json', 'selected_segments.json', 'clip_manifest.json', 'export_results.json'], 'not_real_ai_model': True, 'not_delivery_evidence': True}

```

## stderr tail
```text

```
