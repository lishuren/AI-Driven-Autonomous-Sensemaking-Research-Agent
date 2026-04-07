<#
.SYNOPSIS
    Two-step GraphRAG workflow for D:\Mainstream:
    1. Convert source files into GraphRAG input text with a controllable char cap
    2. Run GraphRAG indexing on the prepared project
    3. Generate five analysis reports

.USAGE
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -CheckShardStatus
#>
param(
    [switch]$SkipConvert,
    [switch]$SkipIndex,
    [switch]$CheckShardStatus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:DISABLE_AIOHTTP_TRANSPORT = "True"

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
$OllamaBaseUrl  = "http://localhost:11434"

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

function Wait-Ollama {
    param(
        [int]$TimeoutSeconds = 300,
        [int]$PollIntervalSeconds = 10
    )
    $OllamaUrl = "http://localhost:11434/api/tags"
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking Ollama is ready at $OllamaUrl (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        try {
            $Response = Invoke-WebRequest -Uri $OllamaUrl -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            if ($Response.StatusCode -eq 200) {
                Log "Ollama is ready."
                return
            }
        } catch {
            # Not ready yet, keep waiting
        }
        $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Ollama not ready, retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Ollama did not become ready within $TimeoutSeconds seconds. Ensure Ollama is running and gemma4:e4b is available."
}

function Wait-OllamaModel {
    param(
        [string]$ModelName,
        [int]$TimeoutSeconds = 1200,
        [int]$PollIntervalSeconds = 20
    )
    $GenerateUrl = "$OllamaBaseUrl/api/generate"
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking model readiness: $ModelName (timeout=$TimeoutSeconds s)..."

    while ((Get-Date) -lt $Deadline) {
        try {
            $Body = @{
                model  = $ModelName
                prompt = "ping"
                stream = $false
                options = @{ num_predict = 1 }
            } | ConvertTo-Json -Depth 5

            $Response = Invoke-RestMethod -Uri $GenerateUrl -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 120 -ErrorAction Stop
            if ($null -ne $Response -and $null -ne $Response.response) {
                Log "Model ready: $ModelName"
                return
            }
        } catch {
            # Model may still be loading into memory; keep polling until timeout.
        }

        $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Model not ready yet ($ModelName), retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    throw "Model did not become ready within $TimeoutSeconds seconds: $ModelName"
}

function Wait-OllamaEmbedding {
    param(
        [string]$ModelName,
        [int]$TimeoutSeconds = 600,
        [int]$PollIntervalSeconds = 15
    )
    $EmbeddingsUrl = "$OllamaBaseUrl/api/embeddings"
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking embedding model readiness: $ModelName (timeout=$TimeoutSeconds s)..."

    while ((Get-Date) -lt $Deadline) {
        try {
            $Body = @{
                model  = $ModelName
                prompt = "ping"
            } | ConvertTo-Json -Depth 5

            $Response = Invoke-RestMethod -Uri $EmbeddingsUrl -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
            if ($null -ne $Response -and $null -ne $Response.embedding) {
                Log "Embedding model ready: $ModelName"
                return
            }
        } catch {
            # Keep polling while embeddings model loads.
        }

        $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Embedding model not ready yet ($ModelName), retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    throw "Embedding model did not become ready within $TimeoutSeconds seconds: $ModelName"
}

function Initialize-Settings {
    $SettingsPath = Join-Path $Target "settings.yaml"
    if (Test-Path $SettingsPath) {
        Log "settings.yaml already exists"
        Ensure-SettingsTimeouts -SettingsPath $SettingsPath
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
    Ensure-SettingsTimeouts -SettingsPath $SettingsPath
}

function Ensure-SettingsTimeouts {
    param([string]$SettingsPath)

    if (-not (Test-Path $SettingsPath)) {
        return
    }

    $Content = Get-Content -Path $SettingsPath -Raw
    $Updated = $false

    if ($Content -notmatch 'default_completion_model:[\s\S]*?request_timeout:') {
        $Content = [regex]::Replace(
            $Content,
            '(default_completion_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)',
            "$1    request_timeout: $RequestTimeout`r`n",
            [System.Text.RegularExpressions.RegexOptions]::Multiline
        )
        $Updated = $true
    }

    if ($Content -notmatch 'default_embedding_model:[\s\S]*?request_timeout:') {
        $Content = [regex]::Replace(
            $Content,
            '(default_embedding_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)',
            "$1    request_timeout: $RequestTimeout`r`n",
            [System.Text.RegularExpressions.RegexOptions]::Multiline
        )
        $Updated = $true
    }

    if ($Updated) {
        Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
        Log "Updated settings.yaml with request_timeout=$RequestTimeout for Ollama models"
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
        throw "Convert failed with exit code $LASTEXITCODE"
    }
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/3 GraphRAG index started  method=$GraphMethod"
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    $ShardStatus = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
        Log "Resuming from prior checkpoint"
    }
    $IndexArgs = @(
        "index",
        "--root",   $Target,
        "--method", $GraphMethod
    )
    Log "Running GraphRAG index..."
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GraphRAG index failed with exit code $LASTEXITCODE"
    }
    $ShardStatus["#completed"] = $true
    $ShardStatus["#timestamp"] = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus | ConvertTo-Json | Set-Content $ShardStatusFile -Encoding UTF8
    Log "GraphRAG index complete."
}

function Invoke-ReportStep {
    param(
        [string]$Name,
        [string]$Question,
        [string]$Method = $QueryMethod,
        [string]$ResponseType = "Detailed Report"
    )
    $OutFile = Join-Path $ReportsDir ($Name + ".md")
    Log "Generating report: $Name"
    $QueryArgs = @(
        "query",
        "--target",        $Target,
        "--method",        $Method,
        "--question",      $Question,
        "--response-type", $ResponseType
    )
    $Output = (& $LoaderExe @QueryArgs 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        Log "Report FAILED: $Name" "ERROR"
        throw "Report failed: $Name"
    }
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
        Write-Host "========== RESUMPTION STATUS ==========" -ForegroundColor Cyan
        Write-Host "Last checkpoint: $($Status.'#timestamp')" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To resume from where you left off, run:" -ForegroundColor White
        Write-Host '& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert' -ForegroundColor Green
        Write-Host ""
        Write-Host "This will skip convert (saves 30-40 min) and resume index from the prior point." -ForegroundColor Gray
        Write-Host "LLM response cache is preserved for significant speedup on recomputation." -ForegroundColor Gray
        Write-Host ""
    }
}

Log "=== run_mainstream_analysis.ps1 started ==="
Log "DISABLE_AIOHTTP_TRANSPORT=$($env:DISABLE_AIOHTTP_TRANSPORT)"

if ($CheckShardStatus) {
    Show-ResumptionGuide
    exit 0
}

Test-Prerequisite
Initialize-Settings

if ($SkipConvert) {
    Log "Skipping convert (-SkipConvert flag set)"
} else {
    Invoke-ConvertStep
}

if ($SkipIndex) {
    Log "Skipping index (-SkipIndex flag set)"
} else {
    Wait-Ollama
    Wait-OllamaModel -ModelName $Model
    Wait-OllamaEmbedding -ModelName $EmbeddingModel
    Invoke-IndexStep
}

$Reports = @(
    @{ Name = "analysis_report"; Question = "Provide a comprehensive analysis of this corpus: major themes, key findings, key entities and their relationships, uncertainties, and actionable conclusions. Include supporting evidence for each finding." },
    @{ Name = "system_structure_report"; Question = "Describe the overall system structure: identify the core components and subsystems, their individual responsibilities, the interfaces and contracts between them, dependency relationships, and how the components collaborate to deliver end-to-end functionality." },
    @{ Name = "business_analysis_report"; Question = "Provide a business analysis: identify business objectives and stakeholders, map value drivers and revenue/cost levers, assess risks and opportunities, highlight strategic constraints, and provide recommendations with supporting evidence from the corpus." },
    @{ Name = "flow_analysis_report"; Question = "Provide a flow analysis: describe end-to-end process flows and control flows, identify key decision points and branching logic, highlight bottlenecks or failure points, and suggest optimisations backed by evidence from the corpus." },
    @{ Name = "data_flow_report"; Question = "Provide a data flow analysis: identify all data sources and ingestion paths, describe transformations and enrichment steps, map storage layers and data lineage, highlight data quality risks or gaps, and list governance and compliance checkpoints found in the corpus." }
)

foreach ($r in $Reports) {
    Invoke-ReportStep -Name $r.Name -Question $r.Question
}

Log "=== All done. Reports saved to: $ReportsDir ==="
Write-Host "Reports folder: $ReportsDir" -ForegroundColor Green
Show-ResumptionGuide
