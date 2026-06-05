<#
.SYNOPSIS
Council-of-models Codex review orchestrator: dispatches the current diff to three Codex
model tiers (gpt-5.4-mini / gpt-5.4 / gpt-5.5) for independent review and saves each
output to artifacts/reviews/.

.DESCRIPTION
Composes a short review prompt + a git diff body, then invokes Invoke-CodexAgent.ps1 once
per Council member with -ModelPolicy fixed. Each member's stdout is written to a separate
markdown file under -OutputDir. Triage / aggregation happens in the calling Claude Code
slash command (.claude/commands/codex-review.md), not here.

The script supports -DryRun for safe rehearsal: dispatch arguments are printed but no
Codex CLI calls are made and no files are written.

.PARAMETER DiffSource
Which git diff to review:
  staged   -> git diff --cached
  unstaged -> git diff
  all      -> git diff HEAD     (staged + unstaged)
  HEAD     -> git diff HEAD~1 HEAD (last commit)

.PARAMETER OutputDir
Directory where each Council member's review markdown is saved. Default: artifacts/reviews/.

.PARAMETER CouncilModels
Codex model tiers to dispatch as Council members. Default: gpt-5.4-mini, gpt-5.4, gpt-5.5.

.PARAMETER ReasoningEffort
Reasoning effort passed to each Council member. Default: high (per feedback_codex_model_tier_v2).

.PARAMETER DryRun
Print the dispatch commands without invoking Codex CLI and without writing files.

.PARAMETER AllowedPaths
Forwarded to Invoke-CodexAgent.ps1 (TASK-1057 Layer A guard). Empty = guard skipped.

.PARAMETER AutoRestore
Forwarded to Invoke-CodexAgent.ps1 (TASK-1057 Layer A guard).

.PARAMETER ShowHelp
Print usage banner and exit 1. Also triggered when no parameters are supplied.

.EXAMPLE
pwsh -File artifacts/scripts/Invoke-CodexReview.ps1 -DryRun -DiffSource staged
#>

[CmdletBinding()]
param(
    [ValidateSet('staged','unstaged','all','HEAD')]
    [string]$DiffSource = 'all',

    [string]$OutputDir = 'artifacts/reviews/',

    [string[]]$CouncilModels = @('gpt-5.4-mini','gpt-5.4','gpt-5.5'),

    [string]$ReasoningEffort = 'high',

    [switch]$DryRun = $false,

    [string[]]$AllowedPaths = @(),
    [switch]$AutoRestore = $false,

    [switch]$ShowHelp = $false,

    # TASK-1067: prompt size bounds-check opt-out switch.
    [switch]$SuppressSizeWarn = $false
)

function Write-Usage {
    Write-Host ""
    Write-Host "Invoke-CodexReview.ps1 -- Council-of-models Codex review orchestrator" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  pwsh -File artifacts/scripts/Invoke-CodexReview.ps1 \"
    Write-Host "       -DiffSource <staged|unstaged|all|HEAD> \"
    Write-Host "       [-OutputDir artifacts/reviews/] \"
    Write-Host "       [-CouncilModels gpt-5.4-mini,gpt-5.4,gpt-5.5] \"
    Write-Host "       [-ReasoningEffort high] \"
    Write-Host "       [-DryRun] [-AllowedPaths ...] [-AutoRestore]"
    Write-Host ""
    Write-Host "Example:"
    Write-Host "  pwsh -File artifacts/scripts/Invoke-CodexReview.ps1 -DryRun -DiffSource staged"
    Write-Host ""
    Write-Host "Triage of the three review outputs is performed by the .claude/commands/codex-review.md"
    Write-Host "slash command, not by this script."
    Write-Host ""
}

# Treat "no args" as help request to avoid accidental Codex token spend.
if ($ShowHelp -or $PSBoundParameters.Count -eq 0) {
    Write-Usage
    exit 1
}

# Resolve git diff source. Comma operator preserves single-element arrays
# (otherwise switch unwraps @('diff') to the string 'diff' and splatting it to
# git would pass each character as a separate argument).
[string[]]$diffArgs = switch ($DiffSource) {
    'staged'   { ,@('diff','--cached') }
    'unstaged' { ,@('diff') }
    'all'      { ,@('diff','HEAD') }
    'HEAD'     { ,@('diff','HEAD~1','HEAD') }
}

$diffText = & git @diffArgs 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Write-Error "git diff failed for source '$DiffSource': $diffText"
    exit 3
}

$diffText = $diffText.TrimEnd()
if ([string]::IsNullOrWhiteSpace($diffText)) {
    Write-Host "No diff to review (source: $DiffSource). Exiting cleanly." -ForegroundColor Yellow
    exit 0
}

# Build review prompt. Kept short to leave room for the diff under cmd 8191 limit.
$reviewInstruction = @"
You are one member of a three-model Council reviewing the following git diff from a
council-forge artifact-first workflow repository. Output up to 8 findings ranked by
impact. For each finding, emit:

- severity: critical | high | medium | low | info
- location: file:line or section name
- issue: one line
- suggested_fix: one line
- rationale: brief

Focus: correctness, side-effects, security, schema / contract drift, maintainability.
Skip: pure style nits unless they conceal a defect.

--- DIFF ---
$diffText
"@

$promptSize = $reviewInstruction.Length

# TASK-1067 prompt size bounds-check (warn @ 100000 / reject @ 200000; diff-driven generous bounds per docs/dispatch_prompt_discipline.md)
if (-not $SuppressSizeWarn) {
    if ($promptSize -gt 200000) {
        [Console]::Error.WriteLine("Review prompt size $promptSize exceeds reject limit 200000 chars (per docs/dispatch_prompt_discipline.md). Diff too large; consider narrower commit range. Use -SuppressSizeWarn to bypass.")
        exit 4
    } elseif ($promptSize -gt 100000) {
        [Console]::Error.WriteLine("WARNING: Review prompt size $promptSize exceeds soft limit 100000 chars (per docs/dispatch_prompt_discipline.md). Diff is large; review may be token-expensive. Use -SuppressSizeWarn to silence.")
    }
}

# Resolve OutputDir to a forward-slash relative path for logging consistency.
$normalizedOutputDir = $OutputDir -replace '\\','/'
if (-not $normalizedOutputDir.EndsWith('/')) { $normalizedOutputDir += '/' }

if (-not $DryRun) {
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$commitAnchor = (& git rev-parse --short HEAD 2>$null) -as [string]
if ([string]::IsNullOrWhiteSpace($commitAnchor)) { $commitAnchor = 'unknown' }

$savedFiles = @()
$wrapperPath = Join-Path $PSScriptRoot 'Invoke-CodexAgent.ps1'

foreach ($model in $CouncilModels) {
    if ($DryRun) {
        Write-Host "[DRY-RUN] dispatch: model=$model effort=$ReasoningEffort prompt_size=$promptSize diff_source=$DiffSource" -ForegroundColor DarkCyan
        continue
    }

    Write-Host "[Council] Dispatching to $model (effort=$ReasoningEffort, prompt_size=$promptSize)" -ForegroundColor Cyan

    $invokeArgs = @{
        Prompt           = $reviewInstruction
        Model            = $model
        ModelPolicy      = 'fixed'
        ReasoningEffort  = $ReasoningEffort
        TaskScale        = 'standard'
        ApprovalMode     = 'never'
        AllowedPaths     = $AllowedPaths
        AutoRestore      = [bool]$AutoRestore
        # TASK-1067: review wrapper enforces its own bounds (100k/200k); always bypass dispatch wrapper's 500/5000 bounds downstream.
        SuppressSizeWarn = $true
    }

    $reviewOut = & $wrapperPath @invokeArgs 2>&1 | Out-String
    $exitCode = $LASTEXITCODE

    $safeModel = $model -replace '[^a-zA-Z0-9._-]','_'
    $outFile = Join-Path $OutputDir "$timestamp-$safeModel.md"

    $frontmatter = @"
---
model: $model
effort: $ReasoningEffort
diff_source: $DiffSource
commit_anchor: $commitAnchor
generated_at: $(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')
exit_code: $exitCode
---

"@

    Set-Content -Path $outFile -Value ($frontmatter + $reviewOut) -Encoding UTF8
    $savedFiles += $outFile
    Write-Host "  -> Saved: $outFile (exit=$exitCode)" -ForegroundColor Green
}

if ($DryRun) {
    Write-Host "[DRY-RUN] No Codex dispatch was performed and no files were written." -ForegroundColor DarkCyan
    Write-Host "[DRY-RUN] Council members: $($CouncilModels -join ', ')" -ForegroundColor DarkCyan
    exit 0
}

Write-Host ""
Write-Host "Council review complete. Review files:" -ForegroundColor Cyan
foreach ($f in $savedFiles) { Write-Host "  $f" }
Write-Host ""
Write-Host "Next step: open .claude/commands/codex-review.md (or invoke /codex-review) for triage."
exit 0
