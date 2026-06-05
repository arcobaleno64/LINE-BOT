[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Quiet
)

function ConvertFrom-DotEnvValue {
    param([string]$RawValue)

    $value = $RawValue.Trim()
    if ($value.Length -ge 2) {
        $first = $value[0]
        $last = $value[$value.Length - 1]
        if ($first -eq '"' -and $last -eq '"') {
            $inner = $value.Substring(1, $value.Length - 2)
            return $inner.Replace('\"', '"').Replace('\\', '\')
        }
        if ($first -eq "'" -and $last -eq "'") {
            return $value.Substring(1, $value.Length - 2)
        }
    }

    $commentIndex = $value.IndexOf(' #')
    if ($commentIndex -ge 0) {
        return $value.Substring(0, $commentIndex).TrimEnd()
    }

    return $value.TrimEnd()
}

# Load .env file into the current process environment.
# Existing environment variables win by default so CI/runtime secrets are not silently overwritten.
$envFile = Join-Path $PSScriptRoot '..\..\.env'
if (-not (Test-Path $envFile)) {
    Write-Host "Error: .env file not found in project root." -ForegroundColor Red
    exit 1
}

$loadedCount = 0
$skippedCount = 0

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) {
        return
    }

    if ($line -notmatch '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        if (-not $Quiet) {
            Write-Warning "Skipping invalid .env line: $line"
        }
        return
    }

    $varName = $matches[1].Trim()
    $varValue = ConvertFrom-DotEnvValue $matches[2]
    $existingValue = [System.Environment]::GetEnvironmentVariable($varName, 'Process')

    if (-not $Force -and $null -ne $existingValue) {
        $skippedCount += 1
        if (-not $Quiet) {
            Write-Host "Skipped existing variable: $varName" -ForegroundColor Yellow
        }
        return
    }

    [System.Environment]::SetEnvironmentVariable($varName, $varValue, 'Process')
    $loadedCount += 1
}

if (-not $Quiet) {
    Write-Host "Loaded $loadedCount variables from .env." -ForegroundColor Green
    if ($skippedCount -gt 0) {
        Write-Host "Skipped $skippedCount existing variables. Use -Force to overwrite." -ForegroundColor Yellow
    }
}
