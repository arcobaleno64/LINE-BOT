#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Shared helper functions for GitHub publish scripts (wiki, release).
.DESCRIPTION
    Provides unified auth probing, owner/repo resolution, gh CLI checks,
    and standardised exit codes for push-wiki.ps1 and publish-release.ps1.
#>

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
$script:EXIT_OK              = 0
$script:EXIT_AUTH_MISSING    = 10
$script:EXIT_GH_CLI_MISSING  = 11
$script:EXIT_WIKI_NOT_INIT   = 12
$script:EXIT_REMOTE_UNREACHABLE = 13
$script:EXIT_PRECONDITION_FAIL  = 14
$script:EXIT_PUBLISH_FAIL       = 20

# ---------------------------------------------------------------------------
# Resolve owner/repo from git remote
# ---------------------------------------------------------------------------
function Get-OwnerRepo {
    [CmdletBinding()]
    param(
        [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
    )
    Push-Location $RepoRoot
    try {
        $remote = git remote get-url origin 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot read git remote 'origin'."
        }
        # Match https://github.com/OWNER/REPO or git@github.com:OWNER/REPO
        if ($remote -match 'github\.com[:/]([^/]+)/([^/.]+)') {
            return @{ Owner = $Matches[1]; Repo = $Matches[2] }
        }
        throw "Cannot parse owner/repo from remote: $remote"
    }
    finally { Pop-Location }
}

# ---------------------------------------------------------------------------
# Auth probe: GH_TOKEN / GITHUB_TOKEN env var, then gh auth status
# Returns the token string or $null.
# ---------------------------------------------------------------------------
function Test-GitHubAuth {
    [CmdletBinding()]
    param()

    # 1. Environment variables (CI-friendly)
    foreach ($varName in @('GH_TOKEN', 'GITHUB_TOKEN')) {
        $val = [System.Environment]::GetEnvironmentVariable($varName)
        if ($val) {
            Write-Verbose "Auth: using $varName environment variable."
            return $val
        }
    }

    # 2. gh CLI auth
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        $null = gh auth status 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Verbose "Auth: using gh CLI credential store."
            return '__GH_CLI__'
        }
    }

    return $null
}

# ---------------------------------------------------------------------------
# Check gh CLI availability
# ---------------------------------------------------------------------------
function Test-GhCli {
    [CmdletBinding()]
    param()
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Warning "gh CLI is not installed or not in PATH."
        return $false
    }
    return $true
}

# ---------------------------------------------------------------------------
# Check remote reachability via git ls-remote
# ---------------------------------------------------------------------------
function Test-RemoteReachable {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Url
    )
    $null = git ls-remote --exit-code $Url 2>&1
    return ($LASTEXITCODE -eq 0)
}
