<#
.SYNOPSIS
    Stop the Ollama proxy started by `start_ollama_proxy.ps1`.

.USAGE
    .\tools\stop_ollama_proxy.ps1
#>

param(
    [int]$ProxyPort = 11435,
    [string]$PidFile = 'D:\mainstreamGraphRAG\logs\ollama_proxy.pid'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Log([string]$m) { $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'); Write-Host "[$ts] $m" }

if (Test-Path $PidFile) {
    try {
        $proxyPid = (Get-Content -Path $PidFile -ErrorAction Stop).Trim()
        if ($proxyPid -and ($proxyPid -as [int])) {
            Log "Stopping proxy PID $proxyPid"
            Stop-Process -Id $proxyPid -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 200
            Log "Stopped proxy (requested PID $proxyPid)"
            exit 0
        }
    } catch {
        Log "Failed to stop PID from file: $_"
    }
}

# Fallback: look up process owning the TCP port (Windows)
try {
    $conn = Get-NetTCPConnection -LocalPort $ProxyPort -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn -and $conn.OwningProcess) {
        $proxyPid = $conn.OwningProcess
        Log "Stopping proxy owning port $ProxyPort (PID $proxyPid)"
        Stop-Process -Id $proxyPid -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
        Log "Stopped proxy (PID $proxyPid)"
        exit 0
    }
} catch {}

Log "No running proxy found (pid file missing and no process owning port $ProxyPort)."
exit 1
