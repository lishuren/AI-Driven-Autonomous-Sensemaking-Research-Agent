<#
.SYNOPSIS
    Start the Ollama request-logging proxy and run a small targeted embedding test
    against a handful of documents from the local corpus so you don't need to wait
    for a full index run to reach the failing batch.

.DESCRIPTION
    - Starts `tools\ollama_proxy.py` using the workspace virtualenv Python if available.
    - Selects a small set of files from the corpus (by index, by file name, or last N files).
    - POSTs them to the proxy's `/api/embed` endpoint so the proxy log records the
      exact client request and server response for analysis.

.USAGE
    From the repository root (recommended):
    PowerShell:
        & '.venv\Scripts\Activate.ps1'
        .\tools\start_proxy_and_embed_test.ps1 -SampleCount 5

    Examples:
        # Pick 5 files near the end of the input directory
        .\tools\start_proxy_and_embed_test.ps1 -SampleCount 5

        # Pick starting from index 200 (0-based)
        .\tools\start_proxy_and_embed_test.ps1 -StartIndex 200 -SampleCount 8

        # Pick files around a specific file
        .\tools\start_proxy_and_embed_test.ps1 -AroundFile 'D:\mainstreamGraphRAG\input\doc-01234.txt' -SampleCount 7

        # Keep the proxy running after test (default true to allow running main script)
        .\tools\start_proxy_and_embed_test.ps1 -LeaveProxy

#>

param(
    [int]$SampleCount = 5,
    [int]$StartIndex = -1,
    [string]$AroundFile = '',
    [string]$InputDir = 'D:\mainstreamGraphRAG\input',
    [switch]$LeaveProxy = $true,
    [string]$PythonExe = '',
    [string]$ProxyHost = '127.0.0.1',
    [int]$ProxyPort = 11435,
    [int]$MaxSampleLength = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Log([string]$m) { $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'); Write-Host "[$ts] $m" }

# Resolve repo root and default python
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir
if (-not $PythonExe) {
    $candidate = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $candidate) { $PythonExe = $candidate } else { $PythonExe = 'python' }
}

$ProxyScript = Join-Path $RepoRoot 'tools\ollama_proxy.py'
if (-not (Test-Path $ProxyScript)) { throw "Proxy script not found: $ProxyScript" }

Log "Starting proxy using Python: $PythonExe"
$args = @($ProxyScript, '--host', $ProxyHost, '--port', [string]$ProxyPort)
$proc = Start-Process -FilePath $PythonExe -ArgumentList $args -WorkingDirectory $RepoRoot -NoNewWindow -PassThru
Log "Started proxy (PID=$($proc.Id)) listening on $ProxyHost`:$ProxyPort"

# Wait briefly for proxy to accept connections
$proxyUrl = "http://$ProxyHost`:$ProxyPort/api/embed"
$ready = $false
for ($i=0; $i -lt 15; $i++) {
    try {
        # a quick HEAD-like check: attempt an empty POST ping; may return 400 but confirm socket
        $resp = Invoke-WebRequest -Uri $proxyUrl -Method Options -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        $ready = $true; break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) { Log "Warning: proxy did not respond within timeout; continuing (it may still be starting)." }

# Collect sample files
if (-not (Test-Path $InputDir)) { Log "Input directory not found: $InputDir"; if (-not $LeaveProxy) { Stop-Process -Id $proc.Id -Force }; exit 1 }
$allFiles = Get-ChildItem -Path $InputDir -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 0 } | Sort-Object FullName
if ($allFiles.Count -eq 0) { Log "No files found under $InputDir"; if (-not $LeaveProxy) { Stop-Process -Id $proc.Id -Force }; exit 1 }

# Determine selection range
$total = $allFiles.Count
if ($AroundFile -and (Test-Path $AroundFile)) {
    $full = (Resolve-Path $AroundFile).ProviderPath
    $idx = $allFiles | Select-Object -Index 0 -First 0 # placeholder
    $found = $false
    for ($i=0; $i -lt $total; $i++) { if ($allFiles[$i].FullName -eq $full) { $idx = $i; $found = $true; break } }
    if (-not $found) { Log "Warning: AroundFile not found in input dir; defaulting to last files"; $start = [Math]::Max(0, $total - $SampleCount) } else { $start = [Math]::Max(0, $idx - [Math]::Floor($SampleCount/2)) }
} elseif ($StartIndex -ge 0 -and $StartIndex -lt $total) {
    $start = $StartIndex
} else {
    $start = [Math]::Max(0, $total - $SampleCount)
}
$end = [Math]::Min($total - 1, $start + $SampleCount - 1)

$selected = $allFiles[$start..$end]
Log "Selected $($selected.Count) files (index $start..$end) for embedding test"
foreach ($f in $selected) { Log " - $($f.FullName)" }

# Read file contents and prepare payload
$texts = @()
foreach ($f in $selected) {
    try {
        $txt = Get-Content -Path $f.FullName -Raw -Encoding UTF8
        if ($null -eq $txt) { $txt = '' }
        $txt = $txt -replace '\s+', ' '
        if ($txt.Length -gt $MaxSampleLength) { $txt = $txt.Substring(0, $MaxSampleLength) }
        $texts += $txt
    } catch {
        Log "Failed to read $($f.FullName): $_"; $texts += ''
    }
}

# Build JSON payload and POST to proxy's /api/embed
$payload = @{ model = 'nomic-embed-text'; input = $texts }
$json = $payload | ConvertTo-Json -Depth 10
Log "Posting payload to http://$ProxyHost`:$ProxyPort/api/embed (model=nomic-embed-text, items=$($texts.Count))"
try {
    $resp = Invoke-RestMethod -Uri "http://$ProxyHost`:$ProxyPort/api/embed" -Method Post -ContentType 'application/json' -Body $json -TimeoutSec 300 -ErrorAction Stop
    Log "Received response from embed endpoint: `n$($resp | ConvertTo-Json -Depth 5)"
} catch {
    Log "Embed request failed: $_"
    Log "Check the proxy log at D:\mainstreamGraphRAG\logs\ollama_proxy_requests.log for the exact request/response pair."
}

if (-not $LeaveProxy) {
    Log "Stopping proxy (PID=$($proc.Id))"
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
} else {
    Log "Leaving proxy running. Tail the proxy log while you re-run the full index: D:\mainstreamGraphRAG\logs\ollama_proxy_requests.log"
}

Log "Done. If you saw a 400 in the embed request, copy the REQUEST/RESPONSE block from the proxy log and share it for analysis."
