# Reference Answer Repair Plan

1. Keep the generated project on the local-first shared GUI/CLI pipeline route.
2. Keep User Media Pipeline Contract v1 as bounded local input evidence, not production media processing.
3. Re-run the reference answer project trial after any generation or delivery evidence change.
4. Supply representative real-ASR repeat runs and approved human review evidence before evaluating COMMERCIAL_READY.
- Repair: asr:contract_fixture_verified_not_production_asr
- Repair: commercial_promotion:asr_evidence_tier_not_candidate:contract_fixture
- Repair: commercial_promotion:asr_path_degraded
- Repair: commercial_promotion:asr_quality_not_production_candidate:contract_only
- Repair: commercial_promotion:character_error_rate_unavailable
- Repair: commercial_promotion:fixture_or_non_real_asr_adapter
- Repair: commercial_promotion:missing_reference_transcripts
- Repair: commercial_promotion:token_error_rate_unavailable
- Repair: commercial_readiness:user_media_contract_not_production_media_or_asr
- Repair: commercial_ready:asr_multi_sample_quality_not_pass
- Repair: commercial_ready:human_review_evidence_missing
- Repair: commercial_ready:production_asr_not_verified_true
- Repair: commercial_ready:promotion_decision_not_candidate:COMMERCIAL_BETA_PLUS
- Repair: commercial_ready:promotion_report_has_blockers
- Repair: commercial_ready:ready_adapter_kind_not_real_local_asr
- Repair: commercial_ready:ready_asr_path_degraded
- Repair: commercial_ready:ready_character_error_rate_unavailable_or_high
- Repair: commercial_ready:ready_evidence_tier_insufficient:contract_fixture
- Repair: commercial_ready:ready_reference_transcript_coverage_below_threshold
- Repair: commercial_ready:ready_token_error_rate_unavailable_or_high
- Repair: commercial_ready:reliability_outputs_not_deterministic
- Repair: commercial_ready:reliability_run_count_below_minimum
- Repair: commercial_ready:repeat_reliability_not_pass
- Repair: local_model_adapter:no_real_model_configured_for_reference_trial
- Repair: media_decode:bounded_ffmpeg_extract_verified_not_production_pipeline
- Repair: user_media_pipeline:real_input_contract_verified_not_production_media_pipeline
