param(
    [switch]$Persist
)

$ErrorActionPreference = "SilentlyContinue"

function Resolve-Cmd {
    param([string[]]$Candidates)
    foreach ($c in $Candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            return $c
        }
    }
    return ""
}

$targets = @(
    @{ Name = "AGENT_OS_CODEX_CMD"; Candidates = @("codex") },
    @{ Name = "AGENT_OS_GEMINI_CMD"; Candidates = @("gemini", "gemini-cli", "gcli") },
    @{ Name = "AGENT_OS_CLAUDE_CMD"; Candidates = @("claude", "claude-cli") }
)

Write-Host "Executor setup scan..."

foreach ($t in $targets) {
    $name = $t.Name
    $found = Resolve-Cmd -Candidates $t.Candidates

    if ($found) {
        Set-Item -Path ("Env:" + $name) -Value $found
        Write-Host "[OK] $name = $found (session)"
        if ($Persist) {
            setx $name $found | Out-Null
            Write-Host "[OK] persisted $name"
        }
    }
    else {
        Write-Host "[MISS] $name not found"
    }
}

Write-Host ""
Write-Host "Healthcheck:"
python -m agent_os.apps.cli --healthcheck --repo .

Write-Host ""
Write-Host "Tip: reopen terminal after -Persist to refresh environment."
