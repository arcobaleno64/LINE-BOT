#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Push wiki/ directory contents to the GitHub Wiki repository.
.DESCRIPTION
    Preflight checks (auth, wiki existence) then syncs wiki/ to the .wiki.git repo.
    Prerequisites: The wiki must be initialized through the GitHub web UI first.
    Uses shared helpers from github_publish_common.ps1.
.PARAMETER WhatIf
    Run all preflight checks but skip the actual push.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$scriptDir = $PSScriptRoot
$repoRoot  = Split-Path -Parent $scriptDir

# Load shared helpers
. (Join-Path $scriptDir 'github_publish_common.ps1')

# ---------------------------------------------------------------------------
# 1. Preflight checks
# ---------------------------------------------------------------------------
Write-Host "=== Preflight ===" -ForegroundColor Cyan

# 1a. Auth probe
$auth = Test-GitHubAuth
if (-not $auth) {
    Write-Error "GitHub auth not found. Set GH_TOKEN / GITHUB_TOKEN or run 'gh auth login'."
    exit $EXIT_AUTH_MISSING
}
Write-Host "[OK] GitHub auth detected." -ForegroundColor Green

# 1b. Resolve owner/repo
$ownerRepo = Get-OwnerRepo -RepoRoot $repoRoot
$owner = $ownerRepo.Owner
$repo  = $ownerRepo.Repo
Write-Host "[OK] Repository: $owner/$repo" -ForegroundColor Green

# 1c. Wiki source directory
$wikiSource = Join-Path $repoRoot 'wiki'
if (-not (Test-Path $wikiSource)) {
    Write-Error "wiki/ directory not found at $wikiSource"
    exit $EXIT_PRECONDITION_FAIL
}
Write-Host "[OK] wiki/ directory found." -ForegroundColor Green

# 1d. Wiki remote reachability (ls-remote)
$wikiUrl = "https://github.com/$owner/$repo.wiki.git"
Write-Host "Probing wiki remote: $wikiUrl ..." -ForegroundColor Cyan
if (-not (Test-RemoteReachable -Url $wikiUrl)) {
    Write-Error @"
Wiki repository is not reachable. Possible causes:
  - Wiki has not been initialized (create the first page at https://github.com/$owner/$repo/wiki)
  - Wiki is disabled in repository settings
  - Auth token lacks wiki push permission
"@
    exit $EXIT_WIKI_NOT_INIT
}
Write-Host "[OK] Wiki remote reachable." -ForegroundColor Green

Write-Host "=== Preflight PASSED ===" -ForegroundColor Green
if ($WhatIf) {
    Write-Host "WhatIf: Skipping actual push." -ForegroundColor Yellow
    exit $EXIT_OK
}

# ---------------------------------------------------------------------------
# 2. Clone, sync, push
# ---------------------------------------------------------------------------
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "cf-wiki-push-$(Get-Random)"
try {
    Write-Host "Cloning wiki repository..." -ForegroundColor Cyan
    git clone $wikiUrl $tempDir 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone wiki repo at $wikiUrl"
    }

    Write-Host "Copying wiki pages..." -ForegroundColor Cyan
    Get-ChildItem "$tempDir\*" -Exclude '.git' | Remove-Item -Recurse -Force
    Copy-Item "$wikiSource\*" $tempDir -Recurse -Force

    Set-Location $tempDir
    git add -A
    $changes = git status --porcelain
    if (-not $changes) {
        Write-Host "No changes to push." -ForegroundColor Yellow
        exit $EXIT_OK
    }

    git commit -m "docs: update wiki from repo wiki/ directory"
    git push origin master
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed."
    }

    Write-Host "Wiki updated successfully." -ForegroundColor Green
    Write-Host "View at: https://github.com/$owner/$repo/wiki" -ForegroundColor Cyan
}
finally {
    Set-Location $repoRoot
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
}
