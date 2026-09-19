[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $MmArguments
)

$workspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entryPoint = Join-Path $workspaceRoot '.agents\skills\math-modeling\scripts\mm.py'
$projectPython = Join-Path $workspaceRoot '.venv\Scripts\python.exe'

if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
    $python = $projectPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Write-Error 'Python was not found. Restore the project .venv or add python to PATH.'
        exit 2
    }
    $python = $pythonCommand.Source
}

& $python $entryPoint @MmArguments
exit $LASTEXITCODE
