# MATLAB Integration

Use MATLAB MCP for interactive implementation and validation. Use the pipeline evidence gate to connect that MCP work to repeatable case finalization.

## MCP Validation Path

For each MATLAB step:

1. Call `mcp__matlab__check_matlab_code` on the final `.m` script and resolve every reported issue.
2. Call `mcp__matlab__run_matlab_file` and inspect its result.
3. When a test file is declared, call `mcp__matlab__run_matlab_test_file` and require zero failed and zero incomplete tests.
4. Confirm every declared JSON, CSV, MAT, or figure output exists and is final.
5. Record hash-bound evidence:

```powershell
python scripts/record_matlab_validation.py --case-dir <case-dir> `
  --step-name solve --script src/solve.m --test tests/test_solve.m `
  --dependency src/model_core.m `
  --output results/solution.json --output figures/diagnostic.png `
  --confirm-code-analyzer-passed `
  --confirm-script-execution-passed `
  --confirm-unit-tests-passed `
  --notes "Analyzer clean; all tests passed."
```

Do not pass a confirmation flag unless that MCP action was performed successfully in the current validation run. Declare every case-local function or data file that can change the MATLAB result as a dependency. The evidence binds the script, optional test, dependencies, and all declared outputs by SHA-256. Changing any bound file invalidates the pipeline gate.

Configure the corresponding manifest step:

```json
{
  "name": "solve",
  "type": "matlab",
  "runner": "mcp-evidence",
  "script": "src/solve.m",
  "test": "tests/test_solve.m",
  "dependencies": ["src/model_core.m"],
  "outputs": ["results/solution.json", "figures/diagnostic.png"]
}
```

The default evidence path is `results/matlab-validation-<step-name>.json`. Set `evidence` only when a different case-local path is required.

## Batch Path

Set `"runner": "batch"` only after a real `matlab -batch` smoke test succeeds on the current machine. The pipeline then runs Code Analyzer, the script, tests, and output checks in separate batch processes. A detected `matlab.exe` does not prove that batch startup is healthy.

On this Windows R2026a installation (`26.1.0.3203278`), an independent batch process exits with `0xc0000005` in `mwhomesessionmanager_impl.dll` after user code completes whenever `MathWorksServiceHost.exe` is already running. With ServiceHost stopped, the same smoke test exits normally. Preflight therefore reports `matlab_batch.safe_to_start=false` while either `MATLAB.exe` or `MathWorksServiceHost.exe` is present, and the pipeline refuses `runner: batch`. It never terminates those processes automatically.

Prefer `mcp-evidence` when MCP works but independent batch startup is unstable. Do not silently fall back between runners because that would weaken provenance.

## MATLAB File Rules

- Keep `.m` scripts, tests, and outputs inside the case directory.
- Use `matlab.unittest` tests for numerical assertions and failure cases.
- Write headline values to finite JSON scalars when they must enter `result-register.json`.
- Close file handles explicitly. Persistent MCP workspaces can keep `onCleanup` objects alive after a script returns.
- Avoid relying on the MATLAB current folder; derive paths from `mfilename('fullpath')`.
- Keep graphical output deterministic and save figures explicitly when the paper consumes them.
