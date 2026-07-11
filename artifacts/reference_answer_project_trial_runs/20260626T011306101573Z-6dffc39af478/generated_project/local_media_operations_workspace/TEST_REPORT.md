# TEST_REPORT

## Smoke Command
```bash
C:\Users\sunom\AppData\Local\Programs\Python\Python313\python.exe cli.py --input fixtures/media_fixture.json --output-dir .
```

- status: PASS
- returncode: 0
- duration_seconds: 2.944
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260626T011306101573Z-6dffc39af478\generated_project\local_media_operations_workspace`

## commands_run
- C:\Users\sunom\AppData\Local\Programs\Python\Python313\python.exe cli.py --input fixtures/media_fixture.json --output-dir .

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
- asr_status: placeholder_transcription
- asr_adapter_kind: none
- asr_evidence_tier: placeholder
- asr_command: `None`
- asr_returncode: None
- asr_timed_out: False
- asr_schema_valid: False
- asr_output_artifact: `None`
- asr_quality_report: `asr_quality_report.json`
- asr_quality_status: not_ready
- asr_quality_adapter_kind: none
- asr_quality_evidence_tier: none
- asr_quality_sample_count: 1
- asr_quality_successful_samples: 0
- asr_quality_failed_samples: 1
- asr_quality_timeout_samples: 0
- asr_quality_invalid_output_samples: 0
- asr_quality_success_rate: 0.0
- asr_quality_non_empty_text_rate: 0.0
- asr_quality_non_empty_segments_rate: 0.0
- asr_production_candidate: False
- asr_production_verified: False
- asr_production_readiness_blockers: ['no_real_asr_command_configured']
- asr_production_asr: False
- asr_degraded: True
- commercial_promotion_decision: COMMERCIAL_BETA
- commercial_readiness_level: COMMERCIAL_BETA
- commercial_promotion_report: `production_asr_verification_report.json`
- commercial_promotion_blockers: ['commercial_promotion_gate_not_requested', 'missing_real_asr_command', 'fixture_or_non_real_asr_adapter', 'asr_evidence_tier_not_candidate:none', 'asr_quality_not_production_candidate:not_ready', 'sample_count_below_promotion_threshold', 'success_rate_below_promotion_threshold', 'transcript_schema_validation_failed', 'missing_reference_transcripts', 'token_error_rate_unavailable', 'character_error_rate_unavailable', 'user_media_input_not_verified', 'production_decode_evidence_missing', 'asr_path_degraded']
- production_reliability_status: not_ready
- production_reliability_run_count: 0
- production_reliability_report: `production_reliability_report.json`
- commercial_ready_decision: NOT_READY
- commercial_ready_report: `commercial_ready_report.json`
- commercial_ready_blockers: ['commercial_ready_gate_not_requested', 'ready_adapter_kind_not_real_local_asr', 'ready_evidence_tier_insufficient:none', 'promotion_decision_not_candidate:COMMERCIAL_BETA', 'promotion_report_has_blockers', 'production_asr_not_verified_true', 'ready_asr_path_degraded', 'asr_multi_sample_quality_not_pass', 'ready_sample_count_below_minimum', 'ready_failed_samples_above_threshold', 'ready_reference_transcript_coverage_below_threshold', 'ready_token_error_rate_unavailable_or_high', 'ready_character_error_rate_unavailable_or_high', 'repeat_reliability_not_pass', 'reliability_run_count_below_minimum', 'reliability_outputs_not_deterministic', 'ready_production_decode_missing', 'ready_user_media_input_missing', 'human_review_evidence_missing']
- transcription_status: placeholder_transcription
- transcription_tool: none
- transcription_not_production_asr: False
- transcription_output_artifact: `transcription_adapter_result.json`
- ffprobe_status: local_tool_verified
- ffmpeg_status: local_tool_verified
- capability_manifest: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260626T011306101573Z-6dffc39af478\generated_project\local_media_operations_workspace\capability_manifest.json`

## stdout tail
```text
{'status': 'degraded', 'mode': 'local_fixture_processing', 'capability_manifest': 'capability_manifest.json', 'media_manifest': '', 'user_media_contract': {}, 'selected_adapter': 'local_tool_verified', 'artifacts': ['stage_plan.json', 'media_manifest.json', 'audio_chunk_manifest.json', 'transcript_merged.json', 'segment_analysis.json', 'selected_segments.json', 'clip_manifest.json', 'export_results.json'], 'not_real_ai_model': True, 'not_delivery_evidence': True}

```

## stderr tail
```text

```
