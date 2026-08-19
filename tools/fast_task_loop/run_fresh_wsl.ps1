[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TaskDirectory,

    [ValidateRange(1, 99)]
    [int]$Round = 1,

    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 360,

    [string]$Model = "gpt-5.6-sol",

    [string]$Distro = "",

    [string]$PromptPath = "",

    [switch]$KeepWorkspace
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $argsList = @()
    if (-not [string]::IsNullOrWhiteSpace($Distro)) {
        $argsList += @("-d", $Distro)
    }
    $argsList += @("--", "wslpath", "-a", "-u", $WindowsPath)

    $output = & wsl.exe @argsList 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "wslpath failed for '$WindowsPath': $($output | Out-String)"
    }
    return (($output | Out-String).Trim())
}

$taskRoot = (Resolve-Path -LiteralPath $TaskDirectory).Path
$participant = Join-Path $taskRoot "participant"
if (-not (Test-Path -LiteralPath (Join-Path $participant "TASK.md") -PathType Leaf)) {
    throw "Missing participant/TASK.md under $taskRoot"
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "../..")).Path
if ([string]::IsNullOrWhiteSpace($PromptPath)) {
    $PromptPath = Join-Path $repoRoot "prompts/fast_task_loop/FRESH_AGENT_PROMPT.md"
}
$prompt = (Resolve-Path -LiteralPath $PromptPath).Path

$attemptName = "fresh_{0:D2}" -f $Round
$attempt = Join-Path (Join-Path $taskRoot "attempts") $attemptName
if (Test-Path -LiteralPath $attempt) {
    Remove-Item -LiteralPath $attempt -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $attempt "output") -Force | Out-Null

$slug = [regex]::Replace((Split-Path -Leaf $taskRoot), "[^A-Za-z0-9_.-]", "-")
$token = [Guid]::NewGuid().ToString("N").Substring(0, 10)
$wslWorkspace = "/tmp/paper2ale-fast/$slug-r$Round-$token"

$participantWsl = Convert-ToWslPath $participant
$attemptWsl = Convert-ToWslPath $attempt
$promptWsl = Convert-ToWslPath $prompt

$bashScriptPath = Join-Path $attempt "_run_fresh_agent.sh"
$bashScript = @'
#!/usr/bin/env bash
set -uo pipefail

participant="$1"
workspace="$2"
prompt="$3"
attempt="$4"
timeout_seconds="$5"
model="$6"
keep_workspace="$7"

rm -rf "$workspace"
mkdir -p "$workspace"
rm -rf "$attempt/output"
mkdir -p "$attempt/output"
cp -a "$participant"/. "$workspace"/

if ! command -v codex >/dev/null 2>&1; then
  printf '%s\n' 'codex is not installed or not on PATH in WSL' > "$attempt/agent_stderr.txt"
  printf '%s\n' '127' > "$attempt/codex_exit_code.txt"
  exit 0
fi

if ! command -v timeout >/dev/null 2>&1; then
  printf '%s\n' 'GNU timeout is not installed in WSL' > "$attempt/agent_stderr.txt"
  printf '%s\n' '127' > "$attempt/codex_exit_code.txt"
  exit 0
fi

cd "$workspace"
set +e
timeout --signal=TERM --kill-after=15s "${timeout_seconds}s" \
  codex exec \
    --ephemeral \
    --skip-git-repo-check \
    --sandbox workspace-write \
    --ask-for-approval never \
    --color never \
    --model "$model" \
    --output-last-message "$workspace/agent_final.txt" \
    -C "$workspace" \
    - \
  < "$prompt" \
  > "$attempt/agent_stdout.txt" \
  2> "$attempt/agent_stderr.txt"
code=$?
set -e

printf '%s\n' "$code" > "$attempt/codex_exit_code.txt"
if [[ -f "$workspace/agent_final.txt" ]]; then
  cp "$workspace/agent_final.txt" "$attempt/agent_final.txt"
fi
if [[ -d "$workspace/output" ]]; then
  cp -a "$workspace/output"/. "$attempt/output"/
  find "$workspace/output" -type f -printf '%P\n' | LC_ALL=C sort > "$attempt/output_files.txt"
else
  : > "$attempt/output_files.txt"
fi

if [[ "$keep_workspace" == "true" ]]; then
  printf '%s\n' "$workspace" > "$attempt/wsl_workspace.txt"
else
  rm -rf "$workspace"
fi
exit 0
'@

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($bashScriptPath, $bashScript, $utf8NoBom)
$bashScriptWsl = Convert-ToWslPath $bashScriptPath

$wslArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Distro)) {
    $wslArgs += @("-d", $Distro)
}
$wslArgs += @(
    "--", "bash", $bashScriptWsl,
    $participantWsl,
    $wslWorkspace,
    $promptWsl,
    $attemptWsl,
    [string]$TimeoutSeconds,
    $Model,
    $(if ($KeepWorkspace) { "true" } else { "false" })
)

$timer = [System.Diagnostics.Stopwatch]::StartNew()
& wsl.exe @wslArgs
$wslExitCode = $LASTEXITCODE
$timer.Stop()

Remove-Item -LiteralPath $bashScriptPath -Force -ErrorAction SilentlyContinue

$codexExitCode = $null
$exitCodePath = Join-Path $attempt "codex_exit_code.txt"
if (Test-Path -LiteralPath $exitCodePath -PathType Leaf) {
    $parsed = 0
    if ([int]::TryParse((Get-Content -LiteralPath $exitCodePath -Raw).Trim(), [ref]$parsed)) {
        $codexExitCode = $parsed
    }
}

$outputFiles = @()
$outputRoot = Join-Path $attempt "output"
if (Test-Path -LiteralPath $outputRoot -PathType Container) {
    $outputFiles = @(Get-ChildItem -LiteralPath $outputRoot -Recurse -File | ForEach-Object {
        $_.FullName.Substring($outputRoot.Length).TrimStart(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    })
}

$run = [ordered]@{
    round = $Round
    model = $Model
    timeout_seconds = $TimeoutSeconds
    elapsed_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
    wsl_distro = $(if ([string]::IsNullOrWhiteSpace($Distro)) { $null } else { $Distro })
    wsl_exit_code = $wslExitCode
    codex_exit_code = $codexExitCode
    timed_out = ($codexExitCode -eq 124 -or $codexExitCode -eq 137)
    output_files = $outputFiles
    note = "The task evaluator, not the Codex process exit code, decides whether the attempt passed."
}
$runJson = $run | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $attempt "run.json"), $runJson + [Environment]::NewLine, $utf8NoBom)

Write-Output ($run | ConvertTo-Json -Depth 5 -Compress)

if ($wslExitCode -ne 0 -or $codexExitCode -eq 127 -or $null -eq $codexExitCode) {
    exit 2
}
exit 0
