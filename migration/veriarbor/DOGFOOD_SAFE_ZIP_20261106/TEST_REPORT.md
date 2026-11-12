# Test Report — Safe ZIP Path Validator

Command:

```powershell
D:\anaconda\python.exe -X utf8 -m unittest discover -s tests -v
```

Result: **OK**

```text
Ran 8 tests in 0.001s
OK
EXIT_CODE=0
```

Coverage:

- plain path
- backslash separator normalization
- leading dot segment rejection
- parent traversal rejection (`..`, nested traversal)
- absolute path / backslash root / drive-letter rejection
- NUL rejection
- empty / dot / duplicate-separator rejection
- non-string rejection
