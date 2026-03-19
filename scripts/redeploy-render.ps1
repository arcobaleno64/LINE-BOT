param(
    [string]$DeployHook
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DeployHook)) {
    $DeployHook = $env:RENDER_DEPLOY_HOOK
}

if ([string]::IsNullOrWhiteSpace($DeployHook)) {
    throw "Missing deploy hook. Set RENDER_DEPLOY_HOOK env var or pass -DeployHook."
}

Write-Host "Triggering Render deploy..."

$response = Invoke-WebRequest -Uri $DeployHook -Method Post -UseBasicParsing

if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
    Write-Host "Deploy trigger sent successfully. HTTP $($response.StatusCode)"
    exit 0
}

throw "Deploy trigger failed. HTTP $($response.StatusCode)"
