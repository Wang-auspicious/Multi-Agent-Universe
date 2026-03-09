Summary (local fallback)
- Executor: shell
- Review: Command failed ((Get-ChildItem -Recurse -File -Filter *.py -ErrorAction SilentlyContinue | Measure-Object).Count): exit_code=126
- Output:
$ (Get-ChildItem -Recurse -File -Filter *.py -ErrorAction SilentlyContinue | Measure-Object).Count
Command not in whitelist: (get-childitem