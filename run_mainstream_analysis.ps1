<#
.SYNOPSIS
    Two-step GraphRAG workflow for D:\Mainstream:
    1. Convert source files into GraphRAG input text with a controllable char cap
    2. Run GraphRAG indexing on the prepared project
    3. Generate five analysis reports

.USAGE
    # From any PowerShell prompt — no activation needed:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"

    # Skip conversion if input/ is already prepared:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert

    # Skip indexing and only regenerate reports:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipIndex
    
    # Check resumption status:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -CheckShardStatus
#>
param(
    [switch]$SkipConvert,
    [switch]$SkipIndex,
    [switch]$CheckShardStatus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Workaround for LiteLLM aiohttp session-leak warnings in long GraphRAG runs.
# Force httpx transport for this process.
$env:DISABLE_AIOHTTP_TRANSPORT = "True"

# ── Configuration ────────────────────────────────────────────────────────────

$LoaderExe   = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe"
$GraphRagExe = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe"
$Source      = "D:\Mainstream"
$Target      = "D:\mainstreamGraphRAG"
$ReportsDir  = Join-Path $Target "reports"
$LogFile     = Join-Path $Target "run_mainstream_analysis.log"

$Provider       = "ollama"
$Model          = "gemma4:e4b"
$EmbeddingModel = "nomic-embed-text"
$QueryMethod    = "global"
$RequestTimeout = 1800
$ConvertMaxChars = 500000
$GraphMethod    = "standard"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-Prerequisite {
    if (-not (Test-Path $LoaderExe))   { throw "graphragloader.exe not found: $LoaderExe" }
    if (-not (Test-Path $GraphRagExe)) { throw "graphrag.exe not found: $GraphRagExe" }
    if (-not (Test-Path $Source))      { throw "Source directory not found: $Source" }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
}

function Initialize-Settings {
    $SettingsPath = Join-Path $Target "settings.yaml"
    if (Test-Path $SettingsPath) {
        Log "settings.yaml already exists: $SettingsPath"
        return
    }

    Log "Generating settings.yaml"
    $InitArgs = @(
        "init",
        "--target",          $Target,
        "--provider",        $Provider,
        "--model",           $Model,
        "--embedding-model", $EmbeddingModel,
        "--request-timeout", $RequestTimeout
    )

    & $LoaderExe @InitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to generate settings.yaml"
    }
}

function Invoke-ConvertStep {
    Log "Step 1/3 Convert started  max_chars=$ConvertMaxChars"

    $ConvertArgs = @(
        "convert",
        "--source",          $Source,
        "--target",          $Target,
        "--include-code",
        "--max-chars",       $ConvertMaxChars
    )

    & $LoaderExe @ConvertArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Convert failed with exit code $LASTEXITCODE. Check $LogFile for details."
    }
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/3 GraphRAG index started  method=$GraphMethod  model=$Model  [100-row shard recovery enabled]"

    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    
    # Load or initialize shard status
    $ShardStatus = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
        Log "Resuming from shard status file: $($ShardStatus.Keys.Count) checkpoints tracked"
    }
    
    $IndexArgs = @(
        "index",
        "--root",   $Target,
        "--method", $GraphMethod
    )

    Log "Running full GraphRAG index (checkpoint recovery on interrupt)"
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GraphRAG index failed with exit code $LASTEXITCODE. Check $LogFile for details."
    }
    
    # Mark index as complete
    $ShardStatus["#completed"] = $true
    $ShardStatus["#timestamp"] = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus | ConvertTo-Json | Set-Content $ShardStatusFile -Encoding UTF8
    
    Log "GraphRAG index complete. Checkpoint file updated."
}

function Invoke-ReportStep {
    param(
        [string]$Name,
        [string]$Question,
        [string]$Method       = $QueryMethod,
        [string]$ResponseType = "Detailed Report"
    )

    $OutFile = Join-Path $ReportsDir ($Name + ".md")
    Log "Step 3/3 Generating report: $Name  ->  $OutFile"

    $QueryArgs = @(
        "query",
        "--target",        $Target,
        "--method",        $Method,
        "--question",      $Question,
        "--response-type", $ResponseType
    )

    $Output = (& $LoaderExe @QueryArgs 2>&1 | Out-String).Trim()

    if ($LASTEXITCODE -ne 0) {
        Log "Report FAILED: $Name  exit=$LASTEXITCODE" "ERROR"
        Log $Output "ERROR"
        throw "Report failed: $Name"
    }

    # Prepend a Markdown title so each file is self-describing
    $Header = "# $Name`n`n> Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n"
    Set-Content -Path $OutFile -Value ($Header + $Output) -Encoding UTF8
    Log "Saved: $OutFile"
}

function Get-ShardStatus {
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    if (Test-Path $ShardStatusFile) {
        return Get-Content $ShardStatusFile -Raw | ConvertFrom-Json
    }
    return $null
}

function Show-ResumptionGuide {
    $Status = Get-ShardStatus
    if ($Status) {
        Write-Host ""
        Write-Host "╔════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
        Write-Host "║ RESUMPTION STATUS                                                      ║" -ForegroundColor Cyan
        Write-Host "╚════════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
        Write-Host "Last checkpoint: $($Status.'#timestamp')" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To resume from where you left off:" -ForegroundColor White
        Write-Host '  & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert' -ForegroundColor Green
        Write-Host ""
        Write-Host "Cache is preserved. Restarting with -SkipConvert will:" -ForegroundColor Gray
        Write-Host "  • Skip the 30–40 min convert step" -ForegroundColor Gray
        Write-Host "  • Resume index near the previous interrupt point" -ForegroundColor Gray
        Write-Host "  • Reuse LLM response cache (significant speedup)" -ForegroundColor Gray
        Write-Host ""
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────

Log "=== run_mainstream_analysis.ps1 started ==="
Log "LiteLLM transport override: DISABLE_AIOHTTP_TRANSPORT=$($env:DISABLE_AIOHTTP_TRANSPORT)"

if ($CheckShardStatus) {
    Show-ResumptionGuide
    exit 0
}

Test-Prerequisite
Initialize-Settings

# Step 1 — Convert
if ($SkipConvert) {
    Log "Skipping convert step (-SkipConvert flag set)."
} else {
    Invoke-ConvertStep
}

# Step 2 — Index
if ($SkipIndex) {
    Log "Skipping indexing (-SkipIndex flag set)."
} else {
    Invoke-IndexStep
}

# Step 3 — Reports
$Reports = @(
    @{
        Name     = "analysis_report"
        Question = "Provide a comprehensive analysis of this corpus: major themes, key findings, key entities and their relationships, uncertainties, and actionable conclusions. Include supporting evidence for each finding."
    },
    @{
        Name     = "system_structure_report"
        Question = "Describe the overall system structure: identify the core components and subsystems, their individual responsibilities, the interfaces and contracts between them, dependency relationships, and how the components collaborate to deliver end-to-end functionality."
    },
    @{
        Name     = "business_analysis_report"
        Question = "Provide a business analysis: identify business objectives and stakeholders, map value drivers and revenue/cost levers, assess risks and opportunities, highlight strategic constraints, and provide recommendations with supporting evidence from the corpus."
    },
    @{
        Name     = "flow_analysis_report"
        Question = "Provide a flow analysis: describe end-to-end process flows and control flows, identify key decision points and branching logic, highlight bottlenecks or failure points, and suggest optimisations backed by evidence from the corpus."
    },
    @{
        Name     = "data_flow_report"
        Question = "Provide a data flow analysis: identify all data sources and ingestion paths, describe transformations and enrichment steps, map storage layers and data lineage, highlight data quality risks or gaps, and list governance and compliance checkpoints found in the corpus."
    }
)

foreach ($r in $Reports) {
    Invoke-ReportStep -Name $r.Name -Question $r.Question
}

Log "=== All done. Reports saved to: $ReportsDir ==="
Write-Host ""
Write-Host "Reports folder: $ReportsDir" -ForegroundColor Green
Show-ResumptionGuide
