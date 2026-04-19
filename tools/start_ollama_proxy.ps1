<#
.SYNOPSIS
    Start the simple Ollama HTTP logging proxy in the background and write its PID.

.DESCRIPTION
    - Starts `tools\ollama_proxy.py` with the workspace venv Python when available.
    - Writes the proxy PID to a pid file so it can be stopped later by `stop_ollama_proxy.ps1`.
    - Exits if a process is already listening on the requested port.

.USAGE
    From the repo root:
        .\tools\start_ollama_proxy.ps1

    To specify python or port:
        .\tools\start_ollama_proxy.ps1 -PythonExe .venv\Scripts\python.exe -ProxyPort 11435
#>

param(
    [string]$PythonExe = '',
    [string]$ProxyHost = '127.0.0.1',
    [int]$ProxyPort = 11435,
    [string]$Target = 'http://127.0.0.1:11434'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Log([string]$m) { $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'); Write-Host "[$ts] $m" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir

if (-not $PythonExe) {
    $candidate = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $candidate) { $PythonExe = $candidate } else { $PythonExe = 'python' }
}

$ProxyScript = Join-Path $RepoRoot 'tools\ollama_proxy.py'
if (-not (Test-Path $ProxyScript)) { throw "Proxy script not found: $ProxyScript" }

# logs dir + pid file
$LogDir = 'D:\mainstreamGraphRAG\logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$PidFile = Join-Path $LogDir 'ollama_proxy.pid'

# check if port is already in use
$portOpen = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $async = $tcp.BeginConnect($ProxyHost, $ProxyPort, $null, $null)
    $wait = $async.AsyncWaitHandle.WaitOne(250)
    if ($wait -and $tcp.Connected) { $portOpen = $true }
    $tcp.Close()
} catch {}

if ($portOpen) {
    Log "Port $ProxyHost`:$ProxyPort appears in use — proxy may already be running."
    if (Test-Path $PidFile) { $existing = Get-Content $PidFile -ErrorAction SilentlyContinue; Log "Existing PID file: $PidFile -> $existing" }
    Log "If you want to restart the proxy, run: .\tools\stop_ollama_proxy.ps1 ; then re-run this script."
    exit 0
}

Log "Starting Ollama proxy using Python: $PythonExe"
$args = @($ProxyScript, '--host', $ProxyHost, '--port', [string]$ProxyPort, '--target', $Target)
$proc = Start-Process -FilePath $PythonExe -ArgumentList $args -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru

# persist PID
try {
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
    Log "Started proxy (PID=$($proc.Id)); PID written to $PidFile"
} catch {
    Log "Started proxy (PID=$($proc.Id)) — failed to write PID file: $_"
}

Log "Proxy is forwarding to $Target and logging to: D:\mainstreamGraphRAG\logs\ollama_proxy_requests.log"
Log "To stop: .\tools\stop_ollama_proxy.ps1"
