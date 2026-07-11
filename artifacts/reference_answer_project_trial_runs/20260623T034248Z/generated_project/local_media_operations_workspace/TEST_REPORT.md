# TEST_REPORT

## Smoke Command
```bash
D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .
```

- status: FAIL
- returncode: 1
- duration_seconds: 0.207
- cwd: `D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace`

## commands_run
- D:\anaconda\python.exe cli.py --input fixtures/media_fixture.json --output-dir .

## results
- exit_code: 1
- status: FAIL

## adapter_status
- adapter_status: unavailable
- selected_adapter: local_tool_unavailable

## stdout tail
```text

```

## stderr tail
```text
Traceback (most recent call last):
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\real_asr_adapter_contract.py", line 16, in <module>
    import asr_evidence_tier
ModuleNotFoundError: No module named 'asr_evidence_tier'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\local_media_adapter.py", line 28, in <module>
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\real_asr_adapter_contract.py", line 18, in <module>
    from scripts import asr_evidence_tier
ImportError: cannot import name 'asr_evidence_tier' from 'scripts' (unknown location)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\cli.py", line 4, in <module>
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\orchestrator.py", line 3, in <module>
    import local_media_adapter
  File "D:\CGKN\artifacts\reference_answer_project_trial_runs\20260623T034248Z\generated_project\local_media_operations_workspace\local_media_adapter.py", line 30, in <module>
ImportError: cannot import name 'real_asr_adapter_contract' from 'scripts' (unknown location)

```
