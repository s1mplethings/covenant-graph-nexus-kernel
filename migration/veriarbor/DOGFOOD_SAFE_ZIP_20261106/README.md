# Safe ZIP Path Validator (VeriArbor Dogfooding)

A small, real engineering task: normalize ZIP entry names safely to prevent
Zip Slip path traversal. It is independent of the Promotion Studio M12 task.

## API

```python
from safe_zip_path import normalize_entry
normalize_entry("docs/readme.txt")  # "docs/readme.txt"
normalize_entry("../secret")        # ValueError
```

## Acceptance

```powershell
python -m unittest discover -s tests -v
```

The independent test suite covers plain paths, backslash normalization,
traversal, absolute paths, drive letters, NUL, empty/dot segments and
non-string input.
