<#
.SYNOPSIS
    Fast-processing variant of run_mainstream_analysis.ps1 targeting 48-72h completion.

    Key differences from the standard script:
      - Max chars per document : 100,000  (was 500,000) — ~5x fewer chars ingested
      - GraphRAG indexing method: fast    (was standard) — lighter extraction algorithms
      - Chunk size             : 2,000    (was 1,200)   — ~40 % fewer text units → fewer LLM calls
      - Chunk overlap          : 150      (was 100)
      - Dual-model strategy    : small model for indexing, larger model for reports

    Default model split:
      -IndexModel  gemma4:e2b  — fits entirely in 8 GB VRAM, fast entity extraction
      -ReportModel gemma4:e4b  — higher quality for final report synthesis

.USAGE
    # First run (convert + index + reports):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1"

    # Resume after interruption (reuse existing input/cache):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert

    # Reports only (after index finishes):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert -SkipIndex

    # Status check (no workflow steps executed):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -CheckShardStatus

    # Override either model independently:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -IndexModel "gemma4:e2b" -ReportModel "gemma4:e4b"
#>
param(
    [switch]$SkipConvert,
    [switch]$SkipIndex,
    [switch]$CheckShardStatus,
    # Small, fast model used during GraphRAG indexing (entity extraction).
    # gemma4:e2b fits fully in 8 GB VRAM with ~3 GB headroom — no CPU offload.
    [string]$IndexModel  = "gemma4:e2b",
    # Higher-quality model used only for the 5 final report queries.
    # Runs after indexing is complete; each query is a single LLM call.
    [string]$ReportModel = "gemma4:e4b"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:DISABLE_AIOHTTP_TRANSPORT    = "True"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"

# ── Paths ────────────────────────────────────────────────────────────────────
$LoaderExe  = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe"
$GraphRagExe = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe"
$Source     = "D:\Mainstream"
$Target     = "D:\mainstreamGraphRAG"
$ReportsDir = Join-Path $Target "reports"
$LogFile    = Join-Path $Target "run_mainstream_fast.log"   # separate log — does not clobber standard log

# ── FAST-MODE SETTINGS ───────────────────────────────────────────────────────
$Provider       = "ollama"
$EmbeddingModel = "nomic-embed-text"
$QueryMethod    = "global"
$RequestTimeout = 1800

# Reduced from 500,000 — limits how much raw text per file goes into GraphRAG input.
# Effect: convert writes smaller .txt files → fewer / smaller chunks → far fewer LLM calls.
$ConvertMaxChars = 100000

# "fast" uses a lighter entity-extraction algorithm (no claim extraction, fewer passes).
# Effect: each text unit is processed in ~30-50% of the time vs. "standard".
$GraphMethod    = "fast"

# Larger chunks → fewer text units in total → fewer extract_graph LLM calls.
# 2,000 tokens ≈ 40% fewer units than 1,200 (e.g. 30,108 → ~18,000).
$FastChunkSize    = 2000
$FastChunkOverlap = 150

$OllamaBaseUrl = "http://localhost:11434"

# ── Helpers ──────────────────────────────────────────────────────────────────
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
    New-Item -ItemType Directory -Force -Path $Target   | Out-Null
    New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
}

function Get-OllamaExecutable {
    foreach ($CommandName in @("ollama.exe", "ollama")) {
        $Cmd = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Cmd -and $Cmd.Source -and (Test-Path $Cmd.Source)) { return $Cmd.Source }
    }
    @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles  "Ollama\ollama.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Ollama\ollama.exe")
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Get-OllamaTags {
    param([int]$TimeoutSeconds = 5)
    try {
        return Invoke-RestMethod -Uri "$OllamaBaseUrl/api/tags" -Method Get -TimeoutSec $TimeoutSeconds -UseBasicParsing -ErrorAction Stop
    } catch { return $null }
}

function Start-OllamaServer {
    $Existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^ollama(\.exe)?$' -and $_.CommandLine -and $_.CommandLine -match '\bserve\b' } |
        Select-Object -First 1
    if ($Existing) {
        Log "Detected existing ollama serve (PID=$($Existing.ProcessId)); waiting for readiness."
        return
    }
    $Exe = Get-OllamaExecutable
    if (-not $Exe) { throw "Ollama API is not reachable and ollama.exe was not found. Install Ollama or start it manually." }
    Log "Starting ollama serve from $Exe"
    $Proc = Start-Process -FilePath $Exe -ArgumentList "serve" -WindowStyle Hidden -PassThru -ErrorAction Stop
    Log "Started ollama serve (PID=$($Proc.Id))"
}

function Get-OllamaInstalledModels {
    $Tags = Get-OllamaTags -TimeoutSeconds 10
    if (-not $Tags) { throw "Unable to query installed Ollama models from $OllamaBaseUrl/api/tags" }
    $List = @()
    foreach ($m in @($Tags.models)) {
        if ($m.name)  { $List += [string]$m.name  }
        if ($m.model) { $List += [string]$m.model }
    }
    return $List | Where-Object { $_ } | Select-Object -Unique
}

function Test-OllamaModelInstalled {
    param([string]$ModelName, [string[]]$InstalledModels)
    $Req  = $ModelName.ToLowerInvariant()
    $Inst = @($InstalledModels | ForEach-Object { $_.ToLowerInvariant() })
    if ($Inst -contains $Req) { return $true }
    if ($ModelName -notmatch ':') {
        return ($Inst | Where-Object { $_ -like "${Req}:*" } | Select-Object -First 1) -ne $null
    }
    return $false
}

function Confirm-OllamaModelsInstalled {
    param([string[]]$ModelNames)
    $Installed = @(Get-OllamaInstalledModels)
    $Missing   = @($ModelNames | Where-Object { -not (Test-OllamaModelInstalled -ModelName $_ -InstalledModels $Installed) })
    if ($Missing.Count -gt 0) {
        $Cmds = ($Missing | ForEach-Object { "ollama pull $_" }) -join "; "
        throw "Required Ollama model(s) not installed: $($Missing -join ', '). Install them first: $Cmds"
    }
    Log "Verified Ollama models are installed: $($ModelNames -join ', ')"
}

function Test-OllamaMissingModelError {
    param($ErrorRecord)
    $Candidates = @()
    if ($null -ne $ErrorRecord) {
        if ($null -ne $ErrorRecord.ErrorDetails) {
            try { $v = $ErrorRecord.ErrorDetails.Message } catch { $v = $null }
            if ($v) { $Candidates += $v }
        }
        if ($null -ne $ErrorRecord.Exception) {
            try { $v = $ErrorRecord.Exception.Message } catch { $v = $null }
            if ($v) { $Candidates += $v }
        }
        try { $v = $ErrorRecord.ToString() } catch { $v = $null }
        if ($v) { $Candidates += $v }
    } else {
        $Candidates += [string]$ErrorRecord
    }
    foreach ($Msg in ($Candidates | Where-Object { $_ -ne $null -and $_ -ne '' })) {
        if ($Msg -match 'model' -and $Msg -match 'not found') { return $true }
    }
    return $false
}

function Wait-Ollama {
    param([int]$TimeoutSeconds = 300, [int]$PollIntervalSeconds = 10)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $AutoStarted = $false
    Log "Checking Ollama is ready at $OllamaBaseUrl/api/tags (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        if ($null -ne (Get-OllamaTags -TimeoutSeconds 5)) { Log "Ollama is ready."; return }
        if (-not $AutoStarted) { Start-OllamaServer; $AutoStarted = $true }
        $Rem = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Ollama not ready, retrying in $PollIntervalSeconds s... ($Rem s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Ollama did not become ready within $TimeoutSeconds seconds."
}

function Wait-OllamaModel {
    param([string]$ModelName, [int]$TimeoutSeconds = 1200, [int]$PollIntervalSeconds = 20)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking model readiness: $ModelName (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        try {
            $Body = @{ model = $ModelName; prompt = "ping"; stream = $false; options = @{ num_predict = 1 } } | ConvertTo-Json -Depth 5
            $Resp = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/generate" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 120 -ErrorAction Stop
            if ($null -ne $Resp -and $null -ne $Resp.response) { Log "Model ready: $ModelName"; return }
        } catch {
            if (Test-OllamaMissingModelError $_) { throw "Completion model missing: $ModelName. Run: ollama pull $ModelName" }
        }
        $Rem = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Model not ready ($ModelName), retrying in $PollIntervalSeconds s... ($Rem s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Model did not become ready within $TimeoutSeconds s: $ModelName"
}

function Wait-OllamaEmbedding {
    param([string]$ModelName, [int]$TimeoutSeconds = 600, [int]$PollIntervalSeconds = 15)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking embedding model readiness: $ModelName (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        try {
            $Body = @{ model = $ModelName; prompt = "ping" } | ConvertTo-Json -Depth 5
            $Resp = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/embeddings" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
            if ($null -ne $Resp -and $null -ne $Resp.embedding) { Log "Embedding model ready: $ModelName"; return }
        } catch {
            if (Test-OllamaMissingModelError $_) { throw "Embedding model missing: $ModelName. Run: ollama pull $ModelName" }
        }
        $Rem = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Embedding model not ready ($ModelName), retrying in $PollIntervalSeconds s... ($Rem s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Embedding model did not become ready within $TimeoutSeconds s: $ModelName"
}

# Patches settings.yaml with fast-mode chunk sizes.
# Called after every Initialize-Settings so the values survive regeneration.
# Swaps the completion model name inside settings.yaml.
# Called between the index and report phases to hot-swap models.
function Update-SettingsModel {
    param([string]$SettingsPath, [string]$ModelName)
    if (-not (Test-Path $SettingsPath)) { return }

    $Content = Get-Content -Path $SettingsPath -Raw
    # Replace the model: line that immediately follows default_completion_model block.
    $New = [regex]::Replace(
        $Content,
        '(?m)(default_completion_model:.*?\n(?:\s+.+\n)*?\s+model:)\s*\S+',
        "`${1} $ModelName"
    )
    if ($New -ne $Content) {
        Set-Content -Path $SettingsPath -Value $New -Encoding UTF8 -NoNewline
        Log "settings.yaml: completion model set to $ModelName"
    } else {
        Log "settings.yaml: model line not matched — verify settings.yaml format" "WARN"
    }
}

function Update-SettingsChunking {
    param([string]$SettingsPath)
    if (-not (Test-Path $SettingsPath)) { return }

    $Content = Get-Content -Path $SettingsPath -Raw
    $Updated = $false

    # Replace  "  size: <number>"  inside the chunking block.
    $New = [regex]::Replace($Content, '(?m)^(\s+size:)\s*\d+', "`${1} $FastChunkSize")
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    # Replace  "  overlap: <number>"  inside the chunking block.
    $New = [regex]::Replace($Content, '(?m)^(\s+overlap:)\s*\d+', "`${1} $FastChunkOverlap")
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    if ($Updated) {
        Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
        Log "Updated settings.yaml: chunk_size=$FastChunkSize, chunk_overlap=$FastChunkOverlap"
    }
}

function Update-SettingsTimeouts {
    param([string]$SettingsPath)
    if (-not (Test-Path $SettingsPath)) { return }

    $Content = Get-Content -Path $SettingsPath -Raw
    $Updated = $false

    if ($Content -match 'request_timeout:') {
        $Content = $Content -replace 'request_timeout:', 'timeout:'
        $Updated = $true
    }
    if ($Content -notmatch 'default_completion_model:[\s\S]*?timeout:') {
        $Content = [regex]::Replace(
            $Content,
            '(default_completion_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)',
            "$1    timeout: $RequestTimeout`r`n",
            [System.Text.RegularExpressions.RegexOptions]::Multiline
        )
        $Updated = $true
    }
    if ($Content -notmatch 'default_embedding_model:[\s\S]*?timeout:') {
        $Content = [regex]::Replace(
            $Content,
            '(default_embedding_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)',
            "$1    timeout: $RequestTimeout`r`n",
            [System.Text.RegularExpressions.RegexOptions]::Multiline
        )
        $Updated = $true
    }
    if ($Updated) {
        Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
        Log "Updated settings.yaml with timeout=$RequestTimeout for Ollama models"
    }
}

function Initialize-Settings {
    $SettingsPath = Join-Path $Target "settings.yaml"
    if (Test-Path $SettingsPath) {
        Log "settings.yaml already exists"
    } else {
        Log "Generating settings.yaml (init model: $IndexModel)"
        $InitArgs = @(
            "init",
            "--target",          $Target,
            "--provider",        $Provider,
            "--model",           $IndexModel,
            "--embedding-model", $EmbeddingModel,
            "--request-timeout", $RequestTimeout
        )
        & $LoaderExe @InitArgs
        if ($LASTEXITCODE -ne 0) { throw "Failed to generate settings.yaml" }
    }
    Update-SettingsTimeouts  -SettingsPath $SettingsPath
    Update-SettingsChunking  -SettingsPath $SettingsPath
    # Ensure settings.yaml reflects the requested index model (survives re-runs).
    Update-SettingsModel     -SettingsPath $SettingsPath -ModelName $IndexModel
}

function Invoke-ConvertStep {
    Log "Step 1/3 Convert started  max_chars=$ConvertMaxChars (fast mode)"
    $ConvertArgs = @(
        "convert",
        "--source",    $Source,
        "--target",    $Target,
        "--include-code",
        "--max-chars", $ConvertMaxChars
    )
    & $LoaderExe @ConvertArgs
    if ($LASTEXITCODE -ne 0) { throw "Convert failed with exit code $LASTEXITCODE" }
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/3 GraphRAG index started  method=$GraphMethod (fast mode)  index-model=$IndexModel"
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    $ShardStatus     = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
        Log "Found prior completion marker; re-running index with preserved input/cache"
    }
    $IndexArgs = @("index", "--root", $Target, "--method", $GraphMethod)
    Log "Running GraphRAG index (fast)..."
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) { throw "GraphRAG index failed with exit code $LASTEXITCODE" }
    $ShardStatus["#completed"]   = $true
    $ShardStatus["#timestamp"]   = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus["#method"]      = $GraphMethod
    $ShardStatus["#index-model"] = $IndexModel
    $ShardStatus["#report-model"]= $ReportModel
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
    if ($LASTEXITCODE -ne 0) { Log "Report FAILED: $Name" "ERROR"; throw "Report failed: $Name" }
    $Header = "# $Name`n`n> Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (fast mode)`n`n"
    Set-Content -Path $OutFile -Value ($Header + $Output) -Encoding UTF8
    Log "Saved: $OutFile"
}

function Get-ShardStatus {
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    if (Test-Path $ShardStatusFile) { return Get-Content $ShardStatusFile -Raw | ConvertFrom-Json }
    return $null
}

function Show-ResumptionGuide {
    $Status = Get-ShardStatus
    if ($Status) {
        Write-Host ""
        Write-Host "========== RESUMPTION STATUS ==========" -ForegroundColor Cyan
        Write-Host "Last checkpoint : $($Status.'#timestamp')" -ForegroundColor Yellow
        if ($Status.'#method') { Write-Host "Index method    : $($Status.'#method')" -ForegroundColor Gray }
        if ($Status.'#model')  { Write-Host "Model used      : $($Status.'#model')"  -ForegroundColor Gray }
        Write-Host ""
        Write-Host "To resume (fast mode):" -ForegroundColor White
        Write-Host '& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert' -ForegroundColor Green
        Write-Host ""
        Write-Host "To regenerate reports only:" -ForegroundColor White
        Write-Host '& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert -SkipIndex' -ForegroundColor Cyan
        Write-Host ""
    }
}

# ── Entry point ───────────────────────────────────────────────────────────────
Log "=== run_mainstream_fast.ps1 started ==="
Log "FAST MODE: max_chars=$ConvertMaxChars  method=$GraphMethod  chunk_size=$FastChunkSize"
Log "MODELS: index=$IndexModel  report=$ReportModel  embedding=$EmbeddingModel"
Log "DISABLE_AIOHTTP_TRANSPORT=$($env:DISABLE_AIOHTTP_TRANSPORT)"
Log "LITELLM_LOCAL_MODEL_COST_MAP=$($env:LITELLM_LOCAL_MODEL_COST_MAP)"

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
    Confirm-OllamaModelsInstalled -ModelNames @($IndexModel, $EmbeddingModel)
    Wait-OllamaModel     -ModelName $IndexModel
    Wait-OllamaEmbedding -ModelName $EmbeddingModel
    Invoke-IndexStep
}

# ── Swap to report model before generating reports ────────────────────────────
$SettingsPath = Join-Path $Target "settings.yaml"
Log "Switching completion model to $ReportModel for report generation"
Update-SettingsModel -SettingsPath $SettingsPath -ModelName $ReportModel
Confirm-OllamaModelsInstalled -ModelNames @($ReportModel)
Wait-OllamaModel -ModelName $ReportModel

$Reports = @(
    @{ Name = "analysis_report";        Question = "Provide a comprehensive analysis of this corpus: major themes, key findings, key entities and their relationships, uncertainties, and actionable conclusions. Include supporting evidence for each finding." },
    @{ Name = "system_structure_report"; Question = "Describe the overall system structure: identify the core components and subsystems, their individual responsibilities, the interfaces and contracts between them, dependency relationships, and how the components collaborate to deliver end-to-end functionality." },
    @{ Name = "business_analysis_report"; Question = "Provide a business analysis: identify business objectives and stakeholders, map value drivers and revenue/cost levers, assess risks and opportunities, highlight strategic constraints, and provide recommendations with supporting evidence from the corpus." },
    @{ Name = "flow_analysis_report";    Question = "Provide a flow analysis: describe end-to-end process flows and control flows, identify key decision points and branching logic, highlight bottlenecks or failure points, and suggest optimisations backed by evidence from the corpus." },
    @{ Name = "data_flow_report";        Question = "Provide a data flow analysis: identify all data sources and ingestion paths, describe transformations and enrichment steps, map storage layers and data lineage, highlight data quality risks or gaps, and list governance and compliance checkpoints found in the corpus." }
)

foreach ($r in $Reports) {
    Invoke-ReportStep -Name $r.Name -Question $r.Question
}

Log "=== All done (fast mode). Reports saved to: $ReportsDir ==="
Write-Host "Reports folder: $ReportsDir" -ForegroundColor Green
Show-ResumptionGuide
