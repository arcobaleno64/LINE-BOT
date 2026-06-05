<#
.SYNOPSIS
Resilient wrapper for the Codex CLI providing task-scale model selection and multi-tier fallback for API errors.

.DESCRIPTION
Wraps the codex CLI to catch 429 Too Many Requests, 400 Bad Request, and 5xx server errors.
Selects the default model and reasoning effort from the task scale unless explicitly overridden.
Executes standard Exponential Backoff.
If failures persist, dynamically steps through the fallback models for the selected task scale.
If models are exhausted, it switches to a Fallback API key and starts from the top model again.
Returns standard output on success or throws a fatal block if all options are exhausted.
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory=$true)]
    [string]$Prompt,

    [string]$ApprovalMode = "full-auto",

    [ValidateSet("tiny", "docs-only", "standard", "high-risk", "cross-module", "critical", "security", "architecture")]
    [string]$TaskScale = "standard",

    [ValidateSet("auto", "fixed", "fallback")]
    [string]$ModelPolicy = "auto",

    [string]$Model = "",
    
    [string]$ReasoningEffort = "",

    [int]$MaxRetriesPerTier = 2,
    [int]$BaseBackoffSeconds = 2,

    [string]$Executable = "codex.cmd",

    # Layer A of TASK-1057 sub-agent write scope guard.
    # Empty array (default) = guard skipped, backward compatible.
    # Element ending in '/' = directory prefix match; else exact file match.
    # Paths use forward slash (git convention).
    [string[]]$AllowedPaths = @(),
    [switch]$AutoRestore = $false,
    # TASK-1059: deprecated forward of -AutoRestore for backward-compat;
    # caller should migrate to -AutoRestore. Removed in a later task.
    [switch]$AutoRestoreLegacy = $false,

    # TASK-1060: opt-in to include 7 lifecycle dirs in pre-dispatch stash baseline.
    # Default $false = exclude lifecycle from stash so sub-agent sees prereq artifacts;
    # set $true only for wrapper-self-test or strict-enforcement callers that have
    # committed lifecycle artifacts and want full-stash semantics.
    [switch]$IncludeLifecycleInBaseline = $false,

    # TASK-1067: prompt size bounds-check opt-out switch.
    [switch]$SuppressSizeWarn = $false
)

# TASK-1067 prompt size bounds-check (warn @ 500 / reject @ 5000; per docs/dispatch_prompt_discipline.md)
if (-not $SuppressSizeWarn) {
    $_promptSize = $Prompt.Length
    if ($_promptSize -gt 5000) {
        [Console]::Error.WriteLine("Prompt size $_promptSize exceeds reject limit 5000 chars (per docs/dispatch_prompt_discipline.md). Use -SuppressSizeWarn to bypass or rewrite as path-reference.")
        exit 4
    } elseif ($_promptSize -gt 500) {
        [Console]::Error.WriteLine("WARNING: Prompt size $_promptSize exceeds soft limit 500 chars (per docs/dispatch_prompt_discipline.md). Consider path-reference form. Use -SuppressSizeWarn to silence.")
    }
}

# Core Error Patterns to Catch
$RetryPatterns = @(
    "429",
    "Too Many Requests",
    "RateLimitError",
    "400 Bad Request",
    "500 Internal Server",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Timeout",
    "Failed to fetch",
    "ECONNRESET"
)
$RegexPattern = ($RetryPatterns | ForEach-Object { [regex]::Escape($_) }) -join '|'

function Get-TaskScaleProfile {
    param([string]$Scale)

    # TASK-1053 Layer 4: tier ladder v2 -- 3 tiers x effort=high.
    # Mapping of legacy 8-value ValidateSet preserved for backward compat.
    switch ($Scale) {
        { $_ -in @("tiny", "docs-only") } {
            return @{
                Effort = "high"
                Models = @("gpt-5.4-mini", "gpt-5.4", "gpt-5.5")
            }
        }
        "standard" {
            return @{
                Effort = "high"
                Models = @("gpt-5.4", "gpt-5.5", "gpt-5.4-mini")
            }
        }
        { $_ -in @("high-risk", "cross-module", "critical", "security", "architecture") } {
            return @{
                Effort = "high"
                Models = @("gpt-5.5", "gpt-5.4", "gpt-5.4-mini")
            }
        }
    }
}

# region TASK-1059 helpers: stash-based pre-dispatch baseline (Option B per
# artifacts/decisions/TASK-1057.decision.md). Replaces the prior git-status-only
# baseline that destroyed user pre-existing modifications.

function Get-LifecyclePathPrefixes {
    # TASK-1060: 7 dirs whose contents must remain visible to sub-agents during
    # dispatch so they can read prereq task / research / plan artifacts.
    return @(
        'artifacts/tasks/',
        'artifacts/research/',
        'artifacts/plans/',
        'artifacts/code/',
        'artifacts/test/',
        'artifacts/verify/',
        'artifacts/status/'
    )
}

function Test-PathInAllowed {
    param(
        [string]$Path,
        [string[]]$Allowed
    )
    foreach ($a in $Allowed) {
        $aNorm = $a -replace '\\', '/'
        if ($aNorm.EndsWith('/')) {
            if ($Path.StartsWith($aNorm)) { return $true }
        } else {
            if ($Path -eq $aNorm) { return $true }
        }
    }
    return $false
}

function Get-LifecycleUntrackedSnapshot {
    # TASK-1062 Bug A fix: snapshot pre-dispatch untracked files inside the 7
    # lifecycle dirs so the post-dispatch guard can distinguish "user
    # pre-existing untracked" (do not delete) from "sub-agent dispatch-time
    # writes" (still subject to AllowedPaths enforcement).
    # `git hash-object -w` writes the blob into .git/objects so Restore-
    # PostDispatchDelta can later cat-file blob the original content back.
    # Returns hashtable @{ <forward-slash-path> = <sha1-hex>; ... }.
    $snapshot = @{}
    $prefixes = Get-LifecyclePathPrefixes
    $lsArgs = @('ls-files', '--others', '--exclude-standard', '--')
    foreach ($prefix in $prefixes) {
        $lsArgs += $prefix
    }
    $untracked = & git @lsArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return $snapshot }
    foreach ($line in $untracked) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $relPath = $line.Trim() -replace '\\', '/'
        if ([string]::IsNullOrWhiteSpace($relPath)) { continue }
        $hash = & git hash-object -w -- $relPath 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        if ($hash -is [array]) { $hash = $hash[0] }
        $hashStr = ([string]$hash).Trim()
        if ([string]::IsNullOrWhiteSpace($hashStr)) { continue }
        $snapshot[$relPath] = $hashStr
    }
    return ,$snapshot
}

function Save-PreDispatchState {
    # Stash tracked-modified + untracked files so dispatch runs on a clean tree
    # and post-dispatch git status reflects only sub-agent writes.
    # TASK-1060: when -IncludeLifecycle is $false (default), exclude 7 lifecycle
    # dirs from the stash so sub-agents see prereq artifacts.
    # TASK-1062: also returns LifecycleUntrackedSnapshot so post-dispatch guard
    # can classify lifecycle untracked files as user pre-existing vs sub-agent
    # writes via blob hash comparison.
    # Returns [PSCustomObject] @{ StashRef = <ref|null>; LifecycleUntrackedSnapshot = <hashtable> }.
    param(
        [bool]$IncludeLifecycle = $false
    )
    # TASK-1062: capture lifecycle untracked snapshot before any stash so the
    # blob hashes reflect the exact pre-dispatch on-disk state.
    $lifecycleSnapshot = @{}
    if (-not $IncludeLifecycle) {
        $lifecycleSnapshot = Get-LifecycleUntrackedSnapshot
        if ($null -eq $lifecycleSnapshot) { $lifecycleSnapshot = @{} }
    }
    $rawStatus = & git status --porcelain --untracked-files=all 2>&1
    $hasChanges = $false
    foreach ($line in $rawStatus) {
        if (-not [string]::IsNullOrWhiteSpace($line)) { $hasChanges = $true; break }
    }
    if (-not $hasChanges) {
        Write-Host "[GUARD] Pre-dispatch: working tree clean; no stash needed." -ForegroundColor DarkGray
        return [PSCustomObject]@{
            StashRef = $null
            LifecycleUntrackedSnapshot = $lifecycleSnapshot
        }
    }
    $timestamp = Get-Date -Format 'yyyyMMddHHmmss'
    $stashMsg = "TASK-1057 pre-dispatch $timestamp"
    if ($IncludeLifecycle) {
        & git stash push -u -m $stashMsg 2>&1 | Out-Null
    } else {
        # TASK-1060: keep 7 lifecycle dirs visible to sub-agent during dispatch.
        $excludePathspecs = @()
        foreach ($prefix in (Get-LifecyclePathPrefixes)) {
            $excludePathspecs += ":(exclude)$prefix"
        }
        & git stash push -u -m $stashMsg -- @excludePathspecs 2>&1 | Out-Null
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[GUARD] FATAL: git stash push -u failed (exit=$LASTEXITCODE); aborting dispatch." -ForegroundColor Red
        Write-Error "__GUARD_FATAL:[TASK-1057] Pre-dispatch stash failed; cannot establish baseline.__"
        exit 4
    }
    # TASK-1060 R2 mitigation: match stash entry by exact msg literal so a
    # user pre-existing stash@{0} cannot be misclaimed when the exclude filter
    # leaves no changes to save (smoke-B: "No local changes to save" + exit 0).
    $stashList = & git stash list 2>&1
    $stashRef = $null
    foreach ($entry in $stashList) {
        if ($entry -match "^(stash@\{\d+\}):\s.*$([regex]::Escape($stashMsg))\s*$") {
            $stashRef = $matches[1]
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($stashRef)) {
        Write-Host "[GUARD] Pre-dispatch: stash msg '$stashMsg' not found (no non-lifecycle delta); proceeding without stash." -ForegroundColor DarkGray
        return [PSCustomObject]@{
            StashRef = $null
            LifecycleUntrackedSnapshot = $lifecycleSnapshot
        }
    }
    Write-Host "[GUARD] Pre-dispatch state stashed at $stashRef" -ForegroundColor DarkCyan
    return [PSCustomObject]@{
        StashRef = $stashRef
        LifecycleUntrackedSnapshot = $lifecycleSnapshot
    }
}

function Restore-PostDispatchDelta {
    # Targeted restore for the supplied violations list only; never operates on
    # the full repo (root cause of the TASK-1057 destruction incident).
    # TASK-1062: when a violation path appears in $LifecycleSnapshot, recover
    # the pre-dispatch content from the .git/objects blob (written by
    # Get-LifecycleUntrackedSnapshot via `git hash-object -w`) instead of
    # deleting the file -- this preserves user pre-existing untracked
    # lifecycle artifacts that the sub-agent modified.
    param(
        [string[]]$Violations,
        [hashtable]$LifecycleSnapshot = @{}
    )
    foreach ($v in $Violations) {
        if ($LifecycleSnapshot -and $LifecycleSnapshot.ContainsKey($v)) {
            $blobHash = $LifecycleSnapshot[$v]
            $parentDir = Split-Path -Path $v -Parent
            if (-not [string]::IsNullOrWhiteSpace($parentDir) -and -not (Test-Path $parentDir)) {
                New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
            }
            $absPath = Join-Path (Get-Location) $v
            # Byte-exact restore: invoke `git cat-file blob <hash>` via
            # Start-Process with -RedirectStandardOutput so the blob bytes
            # land on disk verbatim (trailing newlines / encoding preserved),
            # bypassing PowerShell's line-stripping text pipeline.
            $proc = Start-Process -FilePath 'git' `
                -ArgumentList @('cat-file', 'blob', $blobHash) `
                -RedirectStandardOutput $absPath `
                -NoNewWindow -Wait -PassThru
            if ($proc.ExitCode -eq 0) {
                Write-Host "  Restored lifecycle untracked (pre-dispatch blob): $v" -ForegroundColor Yellow
                continue
            }
        }
        & git ls-files --error-unmatch $v 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & git checkout HEAD -- $v 2>$null | Out-Null
            Write-Host "  Restored tracked (sub-agent write): $v" -ForegroundColor Yellow
        } else {
            if (Test-Path $v) {
                Remove-Item -Path $v -Force -Recurse -ErrorAction SilentlyContinue
                Write-Host "  Deleted untracked (sub-agent write): $v" -ForegroundColor Yellow
            }
        }
    }
}

function Pop-PreDispatchState {
    # Restore user pre-dispatch state from stash. Conflict -> exit 3 fail-safe;
    # stash entry is preserved (not dropped) for manual resolution.
    param([string]$StashRef)
    if ([string]::IsNullOrWhiteSpace($StashRef)) { return 0 }
    $popOutput = & git stash pop $StashRef 2>&1
    $popExit = $LASTEXITCODE
    $hasConflict = ($popOutput | Out-String) -match 'CONFLICT \('
    if ($popExit -ne 0 -or $hasConflict) {
        Write-Host "[FATAL] git stash pop conflict (exit=$popExit); user pre-dispatch state preserved at $StashRef." -ForegroundColor Red
        Write-Host "        Manual resolution: git stash list ; then git stash apply $StashRef ; resolve conflicts ; git stash drop $StashRef" -ForegroundColor Red
        return 3
    }
    Write-Host "[GUARD] User pre-dispatch state restored from $StashRef." -ForegroundColor DarkCyan
    return 0
}

# endregion TASK-1059 helpers

# TASK-1059: forward deprecated -AutoRestoreLegacy to -AutoRestore.
if ($AutoRestoreLegacy) {
    if ($AutoRestore) {
        Write-Host "[DEPRECATED] -AutoRestore and -AutoRestoreLegacy both set; -AutoRestore wins." -ForegroundColor DarkYellow
    } else {
        Write-Host "[DEPRECATED] -AutoRestoreLegacy maps to -AutoRestore for backward-compat; expect removal in a later task." -ForegroundColor DarkYellow
        $AutoRestore = $true
    }
}

$Profile = Get-TaskScaleProfile -Scale $TaskScale
$EffectiveReasoningEffort = if ([string]::IsNullOrWhiteSpace($ReasoningEffort)) { $Profile.Effort } else { $ReasoningEffort }
$Models = @($Profile.Models)

if (![string]::IsNullOrWhiteSpace($Model)) {
    if ($ModelPolicy -eq "fixed") {
        $Models = @($Model)
    } else {
        $Models = @($Model) + ($Models | Where-Object { $_ -ne $Model })
    }
}

Write-Host "  -> Task Scale: $TaskScale; Model Policy: $ModelPolicy; Reasoning Effort: $EffectiveReasoningEffort" -ForegroundColor Cyan

$IsSuccess = $false
$FinalOutput = ""
# TASK-1053: track last attempt's stdout for best-effort capture even when all
# tiers exhaust. Lets callers (e.g. Invoke-CodexReview.ps1) preserve content
# Codex actually produced even though the wrapper marked the dispatch failed.
$BestEffortOutput = ""

# TASK-1059: snapshot user pre-dispatch state so post-dispatch git status
# reflects only sub-agent writes, never user pre-existing modifications.
# TASK-1062: also capture lifecycle untracked snapshot so post-dispatch guard
# can classify "user pre-existing untracked lifecycle" (do not delete) vs
# "sub-agent dispatch-time write" (still subject to AllowedPaths enforcement).
$preDispatchStashRef = $null
$lifecycleSnapshot = @{}
if ($AllowedPaths.Count -gt 0) {
    $preDispatchState = Save-PreDispatchState -IncludeLifecycle:$IncludeLifecycleInBaseline
    if ($null -ne $preDispatchState) {
        $preDispatchStashRef = $preDispatchState.StashRef
        if ($null -ne $preDispatchState.LifecycleUntrackedSnapshot) {
            $lifecycleSnapshot = $preDispatchState.LifecycleUntrackedSnapshot
        }
    }
}

foreach ($model in $Models) {
    Write-Host "  -> Active Model Tier: $model" -ForegroundColor Cyan

    for ($attempt = 0; $attempt -le $MaxRetriesPerTier; $attempt++) {

        # TASK-1053 Layer 3: top-level -a never -s workspace-write replace deprecated --full-auto.
        # Order matters: -a / -s are top-level flags and must precede the `exec` subcommand.
        # ApprovalMode param retained as backward-compat no-op.
        $processArgs = @("-a", "never", "-s", "workspace-write", "exec", "-m", $model)
        if (![string]::IsNullOrWhiteSpace($EffectiveReasoningEffort)) {
            $processArgs += "-c", "model_reasoning_effort=`"$EffectiveReasoningEffort`""
        }

        # TASK-1053 Layer 1: switch to stdin pipe when prompt exceeds 7000 chars
        # to bypass Windows cmd.exe 8191-char command-line limit.
        # TASK-1062 Bug B fix: always pipe via stdin to also avoid the cmd.exe
        # batch-parser truncating multiline prompts at the first LF/CR (codex.cmd
        # would otherwise see only the first line of a multi-line prompt). The
        # 7000-char threshold remains a documented lower-bound rationale, not a
        # cutover condition. Variable name kept for log parity / PR-029 anchors.
        $useStdinPipe = $true
        Write-Host "    [*] Attempt $($attempt+1)/$($MaxRetriesPerTier+1) (stdin_pipe=$useStdinPipe, prompt_size=$($Prompt.Length))..." -ForegroundColor Gray

        $output = $null
        $errText = ""
        $combinedText = ""
        $lastExitCode = 1

        try {
            if ($useStdinPipe) {
                $procOutput = $Prompt | & $Executable $processArgs 2>&1
            } else {
                $procOutput = $null | & $Executable $processArgs 2>&1
            }

            $stdOutLines = @()
            $stdErrLines = @()
            foreach ($line in $procOutput) {
                if ($line -is [System.Management.Automation.ErrorRecord]) {
                    $stdErrLines += $line.Exception.Message
                } else {
                    $stdOutLines += $line
                }
            }

            $outText = $stdOutLines -join "`n"
            $errText = $stdErrLines -join "`n"
            $lastExitCode = $LASTEXITCODE

            $combinedText = "$outText`n$errText"

            # TASK-1053: remember the best-effort stdout (any non-trivial content from
            # any attempt) so the caller can recover Codex output even when the wrapper
            # ultimately decides the dispatch failed.
            if (![string]::IsNullOrWhiteSpace($outText) -and $outText.Length -gt $BestEffortOutput.Length) {
                $BestEffortOutput = $outText
            }

            # Check outcome -- codex CLI 0.128 exit code is the source of truth.
            # The retry-pattern check stays only as a guard for transient errors
            # that might leak through with exit 0 (rare).
            if ($lastExitCode -eq 0 -and -not ($combinedText -match $RegexPattern)) {
                $IsSuccess = $true
                $FinalOutput = $outText
                break
            } else {
                Write-Host "    [!] Intercepted API/Execution Error (ExitCode: $lastExitCode)" -ForegroundColor Yellow
                # TASK-1053 Layer 2: dump last 30 lines of combined stdout/stderr so the
                # underlying CLI error is visible before retry/escalation.
                if (![string]::IsNullOrWhiteSpace($combinedText)) {
                    $tailLines = ($combinedText -split "`n" | Select-Object -Last 30) -join "`n"
                    Write-Host "    [stderr tail]" -ForegroundColor DarkRed
                    Write-Host $tailLines -ForegroundColor DarkRed
                }
            }

        } catch {
            Write-Host "    [!] Process Exception Caught: $($_.Exception.Message)" -ForegroundColor Red
            $combinedText = $_.Exception.Message
        }

        # Calculate backoff if not last attempt
        if ($attempt -lt $MaxRetriesPerTier) {
            if ($combinedText -match $RegexPattern) {
                $sleepTime = [Math]::Pow(2, $attempt) * $BaseBackoffSeconds
                Write-Host "    [Backoff] Target error string matched. Sleeping for $sleepTime seconds..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds $sleepTime
            } else {
                $sleepTime = [Math]::Pow(2, $attempt) * $BaseBackoffSeconds
                Write-Host "    [Backoff] Generic failure. Sleeping for $sleepTime seconds..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds $sleepTime
            }
        }
    } # End Attempt Loop

    if ($IsSuccess) { break }
    Write-Host "  -> Exhausted retries for $model. Escalating tier (fallback)..." -ForegroundColor Magenta
} # End Model Loop

# Layer A: post-dispatch write scope guard (TASK-1057, baseline-fixed by TASK-1059).
# With Save-PreDispatchState stashed user state, git status reflects only sub-agent
# writes. Empty AllowedPaths = skip (backward compatible).
$violationsFound = $false
$violationCount = 0
if ($AllowedPaths.Count -eq 0) {
    Write-Host "[GUARD] skipped (no AllowedPaths configured)" -ForegroundColor DarkGray
} else {
    Write-Host "[GUARD] Post-dispatch write scope check (stash-based baseline)..." -ForegroundColor Cyan
    $rawStatus = & git status --porcelain --untracked-files=all 2>&1
    $changedPaths = @()
    foreach ($line in $rawStatus) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $rest = $line.Substring([Math]::Min(3, $line.Length))
        if ($rest -match ' -> ') { $rest = ($rest -split ' -> ')[-1] }
        $rest = $rest.Trim().Trim('"')
        $rest = $rest -replace '\\', '/'
        if ($rest) { $changedPaths += $rest }
    }
    $violations = @()
    foreach ($p in $changedPaths) {
        if (-not (Test-PathInAllowed -Path $p -Allowed $AllowedPaths)) {
            $violations += $p
        }
    }
    # TASK-1062 Bug A fix: filter out lifecycle untracked paths whose post-
    # dispatch blob hash matches the pre-dispatch snapshot -- these are user
    # pre-existing untracked artifacts the sub-agent did not modify, so they
    # must not be classified as violations (which would lead to deletion).
    if ($violations.Count -gt 0 -and $lifecycleSnapshot -and $lifecycleSnapshot.Count -gt 0) {
        $filtered = @()
        foreach ($p in $violations) {
            if ($lifecycleSnapshot.ContainsKey($p) -and (Test-Path $p)) {
                $postHashRaw = & git hash-object -- $p 2>$null
                if ($LASTEXITCODE -eq 0) {
                    if ($postHashRaw -is [array]) { $postHashRaw = $postHashRaw[0] }
                    $postHash = ([string]$postHashRaw).Trim()
                    if ($postHash -eq $lifecycleSnapshot[$p]) {
                        Write-Host "  [GUARD] Lifecycle pre-existing untracked (unchanged): $p" -ForegroundColor DarkGray
                        continue
                    }
                }
            }
            $filtered += $p
        }
        $violations = $filtered
    }
    if ($violations.Count -gt 0) {
        $violationsFound = $true
        $violationCount = $violations.Count
        Write-Host "[GUARD] Post-dispatch detected sub-agent writes outside AllowedPaths:" -ForegroundColor Red
        foreach ($v in $violations) { Write-Host "  - $v" -ForegroundColor Red }
        if ($AutoRestore) {
            Restore-PostDispatchDelta -Violations $violations -LifecycleSnapshot $lifecycleSnapshot
        } else {
            Write-Host "[GUARD] Detect-only mode (-AutoRestore not set); violations reported but not restored." -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "[GUARD] Post-dispatch check OK; all changes within allowed paths." -ForegroundColor Green
    }
}

# TASK-1059: restore user pre-dispatch state. Conflict -> exit 3 fail-safe.
$popExit = Pop-PreDispatchState -StashRef $preDispatchStashRef
if ($popExit -eq 3) { exit 3 }

# TASK-1059: re-emit violation error after stash pop so guard exit reflects
# the violation outcome (not the dispatch outcome).
if ($violationsFound -and $AutoRestore) {
    Write-Error "__GUARD_VIOLATION:[TASK-1057] Sub-agent wrote $violationCount files outside AllowedPaths.__"
    exit 2
}

# Wrap up
if ($IsSuccess) {
    Write-Output $FinalOutput
    exit 0
} else {
    # TASK-1053: emit best-effort stdout (if any) before the FATAL marker so
    # callers like Invoke-CodexReview.ps1 still capture review text even when
    # the wrapper considers the dispatch failed.
    if (![string]::IsNullOrWhiteSpace($BestEffortOutput)) {
        Write-Output $BestEffortOutput
    }
    Write-Error "__FATAL:[Blocked] All fallback models exhausted for Codex CLI.__`nReview terminal logs or quota statuses."
    exit 1
}
