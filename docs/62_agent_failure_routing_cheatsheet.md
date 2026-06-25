# Agent Failure Routing Cheatsheet

`ERR_UNSUPPORTED_ESM_URL_SCHEME`
-> `post_build_repair.py`
-> deterministic Windows ESM `pathToFileURL` repair

`'vitest' is not recognized`
-> `post_build_repair.py`
-> `missing_vitest` / `missing_test_runner`
-> prefer Node built-in test runner

`body_text_length=0`
-> `visual_evidence.py` + `post_build_repair.py`
-> `page_blank` repair

`startup_failed`
-> `post_build_finalize.py` + `post_build_repair.py`
-> startup diagnostics + start script/static entry repair

candidate bundle sent but final gate rejects
-> correct behavior
-> do not modify `final_delivery_truth.py`

`candidate_diagnostic_bundle.zip` contains `delivery_manifest.json`
-> `artifact_integrity.py`
-> reject bundle

provider HTTP 504 / TLS
-> `provider_generation.py`
-> transport retry / split payload / model routing

`browser_unavailable`
-> `visual_evidence.py`
-> blocked diagnostics only; do not repair project code

`frontend_backend_start_mismatch`
-> `post_build_repair.py`
-> static preview demo data fallback for candidate review
