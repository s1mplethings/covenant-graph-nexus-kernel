# Reference Answer Project Trial Summary

- generated project path: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a\generated_project\local_media_operations_workspace`
- run_dir: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a`
- selected_requirement: `Local video material processing workbench`
- layered status: `PASS`
- score: `100`
- verdict: `PASS`
- screenshot path: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a\generated_project\local_media_operations_workspace\screenshots\delivery_smoke_screenshot.png`
- zip path: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a\generated_project\local_media_operations_workspace\final_project_bundle.zip`
- zip size: `76918`
- delivery_manifest path: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a\generated_project\local_media_operations_workspace\delivery_manifest.json`
- smoke command: `D:\anaconda\python.exe cli.py --input fixtures/sample_audio.wav --output-dir .`
- smoke result: `PASS` returncode `0`
- artifact integrity result: `PASS`
- fixture processing result: `PASS`
- capability manifest result: `PASS` selected_adapter `local_tool_verified`
- user media input status: `verified` path `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T173746405070Z-aee10094895a\generated_project\local_media_operations_workspace\fixtures\sample_audio.wav`
- user media metadata status: `ffprobe_verified` adapter `ffprobe_verified`
- media decode status: `verified` output `media_decode_output.wav`
- ASR status: `asr_contract_fixture_verified` adapter `contract_fixture` tier `contract_fixture` output `real_asr_transcript.json`
- ASR quality status: `contract_only` samples `3` successful `3` failed `0` report `asr_multi_sample_report.json`
- ASR quality rates: success `1.0` text `1.0` segments `1.0` candidate `False` verified `False`
- commercial promotion: `COMMERCIAL_BETA_PLUS` report `production_asr_verification_report.json` blockers `['fixture_or_non_real_asr_adapter', 'asr_evidence_tier_not_candidate:contract_fixture', 'asr_quality_not_production_candidate:contract_only', 'missing_reference_transcripts', 'token_error_rate_unavailable', 'character_error_rate_unavailable', 'asr_path_degraded']`
- production reliability: `not_ready` runs `0` report `production_reliability_report.json`
- commercial ready gate: `NOT_READY` report `commercial_ready_report.json` blockers `['ready_adapter_kind_not_real_local_asr', 'ready_evidence_tier_insufficient:contract_fixture', 'promotion_decision_not_candidate:COMMERCIAL_BETA_PLUS', 'promotion_report_has_blockers', 'production_asr_not_verified_true', 'ready_asr_path_degraded', 'asr_multi_sample_quality_not_pass', 'ready_reference_transcript_coverage_below_threshold', 'ready_token_error_rate_unavailable_or_high', 'ready_character_error_rate_unavailable_or_high', 'repeat_reliability_not_pass', 'reliability_run_count_below_minimum', 'reliability_outputs_not_deterministic', 'human_review_evidence_missing']`
- transcription status: `placeholder_transcription` output `transcription_adapter_result.json`
- commercial readiness result: `COMMERCIAL_BETA_PLUS`
- reference profile alignment result: `PASS` score `100`

## Known Gaps
- asr:contract_fixture_verified_not_production_asr
- commercial_promotion:asr_evidence_tier_not_candidate:contract_fixture
- commercial_promotion:asr_path_degraded
- commercial_promotion:asr_quality_not_production_candidate:contract_only
- commercial_promotion:character_error_rate_unavailable
- commercial_promotion:fixture_or_non_real_asr_adapter
- commercial_promotion:missing_reference_transcripts
- commercial_promotion:token_error_rate_unavailable
- commercial_readiness:user_media_contract_not_production_media_or_asr
- commercial_ready:asr_multi_sample_quality_not_pass
- commercial_ready:human_review_evidence_missing
- commercial_ready:production_asr_not_verified_true
- commercial_ready:promotion_decision_not_candidate:COMMERCIAL_BETA_PLUS
- commercial_ready:promotion_report_has_blockers
- commercial_ready:ready_adapter_kind_not_real_local_asr
- commercial_ready:ready_asr_path_degraded
- commercial_ready:ready_character_error_rate_unavailable_or_high
- commercial_ready:ready_evidence_tier_insufficient:contract_fixture
- commercial_ready:ready_reference_transcript_coverage_below_threshold
- commercial_ready:ready_token_error_rate_unavailable_or_high
- commercial_ready:reliability_outputs_not_deterministic
- commercial_ready:reliability_run_count_below_minimum
- commercial_ready:repeat_reliability_not_pass
- local_model_adapter:no_real_model_configured_for_reference_trial
- media_decode:bounded_ffmpeg_extract_verified_not_production_pipeline
- user_media_pipeline:real_input_contract_verified_not_production_media_pipeline

## Next Recommended Action
Collect representative real-local-ASR repeat runs and approved human review evidence, then rerun the independent COMMERCIAL_READY gate.
