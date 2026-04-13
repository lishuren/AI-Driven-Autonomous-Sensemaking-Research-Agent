<#
.SYNOPSIS
    Two-step GraphRAG workflow for D:\Finance:
    1. Convert source files into GraphRAG input text with a controllable char cap
    2. Run GraphRAG indexing on the prepared project
    3. Generate five analysis reports

.USAGE
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1"
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1" -SkipConvert
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1" -CheckShardStatus
    # After convert completes, a .convert_done.json marker is written to $Target.
    # Restarts automatically skip convert when this file exists.
    # Delete D:\FinanceRAG\.convert_done.json to force a full re-convert.
#>
param(
    [switch]$SkipConvert,
    [switch]$SkipIndex,
    [switch]$CheckShardStatus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:DISABLE_AIOHTTP_TRANSPORT = "True"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"

$LoaderExe   = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe"
$GraphRagExe = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe"
$Source      = "D:\Finance"
$Target      = "D:\FinanceRAG"
$ReportsDir  = Join-Path $Target "reports"
$LogFile     = Join-Path $Target "run_finance_analysis.log"
$ConvertDoneFile = Join-Path $Target ".convert_done.json"   # written after a successful convert; auto-skips re-convert on restart

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

function Get-OllamaExecutable {
    foreach ($CommandName in @("ollama.exe", "ollama")) {
        $Command = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Command -and $Command.Source -and (Test-Path $Command.Source)) {
            return $Command.Source
        }
    }

    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Ollama\ollama.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }

    return $Candidates | Select-Object -First 1
}

function Get-OllamaTags {
    param([int]$TimeoutSeconds = 5)

    $OllamaUrl = "$OllamaBaseUrl/api/tags"
    try {
        return Invoke-RestMethod -Uri $OllamaUrl -Method Get -TimeoutSec $TimeoutSeconds -UseBasicParsing -ErrorAction Stop
    } catch {
        return $null
    }
}

function Start-OllamaServer {
    $ExistingProcess = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^ollama(\.exe)?$' -and
            $_.CommandLine -and
            $_.CommandLine -match '\bserve\b'
        } |
        Select-Object -First 1

    if ($ExistingProcess) {
        Log "Detected existing ollama serve process (PID=$($ExistingProcess.ProcessId)); waiting for API readiness."
        return
    }

    $OllamaExe = Get-OllamaExecutable
    if (-not $OllamaExe) {
        throw "Ollama API is not reachable and ollama.exe was not found. Install Ollama or start it manually."
    }

    Log "Ollama API is not reachable. Starting ollama serve from $OllamaExe"
    $Process = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru -ErrorAction Stop
    Log "Started ollama serve (PID=$($Process.Id))"
}

function Get-OllamaInstalledModels {
    $TagsResponse = Get-OllamaTags -TimeoutSeconds 10
    if (-not $TagsResponse) {
        throw "Unable to query installed Ollama models from $OllamaBaseUrl/api/tags"
    }

    $InstalledModels = @()
    foreach ($ModelInfo in @($TagsResponse.models)) {
        if ($ModelInfo.name) {
            $InstalledModels += [string]$ModelInfo.name
        }
        if ($ModelInfo.model) {
            $InstalledModels += [string]$ModelInfo.model
        }
    }

    return $InstalledModels | Where-Object { $_ } | Select-Object -Unique
}

function Test-OllamaModelInstalled {
    param(
        [string]$ModelName,
        [string[]]$InstalledModels
    )

    $Requested = $ModelName.ToLowerInvariant()
    $NormalizedInstalled = @($InstalledModels | ForEach-Object { $_.ToLowerInvariant() })
    if ($NormalizedInstalled -contains $Requested) {
        return $true
    }

    if ($ModelName -notmatch ':') {
        return ($NormalizedInstalled | Where-Object { $_ -like "${Requested}:*" } | Select-Object -First 1) -ne $null
    }

    return $false
}

function Confirm-OllamaModelsInstalled {
    param([string[]]$ModelNames)

    $InstalledModels = @(Get-OllamaInstalledModels)
    $MissingModels = @()

    foreach ($ModelName in $ModelNames) {
        if (-not (Test-OllamaModelInstalled -ModelName $ModelName -InstalledModels $InstalledModels)) {
            $MissingModels += $ModelName
        }
    }

    if ($MissingModels.Count -gt 0) {
        $PullCommands = ($MissingModels | ForEach-Object { "ollama pull $_" }) -join "; "
        throw "Required Ollama model(s) not installed: $($MissingModels -join ', '). Install them first: $PullCommands"
    }

    Log "Verified Ollama models are installed: $($ModelNames -join ', ')"
}

function Test-OllamaMissingModelError {
    param($ErrorRecord)

    $candidates = @()

    if ($null -ne $ErrorRecord) {
        if ($null -ne $ErrorRecord.ErrorDetails) {
            try {
                $ed = $ErrorRecord.ErrorDetails.Message
            } catch {
                $ed = $null
            }
            if ($ed) { $candidates += $ed }
        }

        if ($null -ne $ErrorRecord.Exception) {
            try {
                $ex = $ErrorRecord.Exception.Message
            } catch {
                $ex = $null
            }
            if ($ex) { $candidates += $ex }
        }

        try {
            $toStr = $ErrorRecord.ToString()
        } catch {
            $toStr = $null
        }
        if ($toStr) { $candidates += $toStr }
    } else {
        $candidates += [string]$ErrorRecord
    }

    foreach ($Message in $candidates | Where-Object { $_ -ne $null -and $_ -ne '' }) {
        if ($Message -match 'model' -and $Message -match 'not found') {
            return $true
        }
    }

    return $false
}

function Wait-Ollama {
    param(
        [int]$TimeoutSeconds = 300,
        [int]$PollIntervalSeconds = 10
    )
    $OllamaUrl = "http://localhost:11434/api/tags"
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $AttemptedAutoStart = $false
    Log "Checking Ollama is ready at $OllamaUrl (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        $Response = Get-OllamaTags -TimeoutSeconds 5
        if ($null -ne $Response) {
            Log "Ollama is ready."
            return
        }

        if (-not $AttemptedAutoStart) {
            Start-OllamaServer
            $AttemptedAutoStart = $true
        }

        $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Ollama not ready, retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Ollama did not become ready within $TimeoutSeconds seconds. Ensure Ollama is installed and startable on this machine."
}

function Wait-OllamaModel {
    param(
        [string]$ModelName,
        [int]$TimeoutSeconds = 3600,
        [int]$PollIntervalSeconds = 60
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

            # Use a long per-call timeout (15 min) — large models like Gemma4
            # can take 5-10 min to initialise on first generate.
            $Response = Invoke-RestMethod -Uri $GenerateUrl -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 900 -ErrorAction Stop
            if ($null -ne $Response -and ($null -ne $Response.response -or $Response.done -eq $true)) {
                Log "Model ready: $ModelName"
                return
            }
        } catch {
            if (Test-OllamaMissingModelError $_) {
                throw "Completion model is missing from Ollama: $ModelName. Install it with: ollama pull $ModelName"
            }
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
            if (Test-OllamaMissingModelError $_) {
                throw "Embedding model is missing from Ollama: $ModelName. Install it with: ollama pull $ModelName"
            }
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
        Update-SettingsTimeouts -SettingsPath $SettingsPath
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
    Update-SettingsTimeouts -SettingsPath $SettingsPath
}

function Update-SettingsTimeouts {
    param([string]$SettingsPath)

    if (-not (Test-Path $SettingsPath)) {
        return
    }

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
    # Write a completion marker so restarts automatically skip convert.
    @{ completed = $true; timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); source = $Source; max_chars = $ConvertMaxChars } |
        ConvertTo-Json | Set-Content $ConvertDoneFile -Encoding UTF8
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/3 GraphRAG index started  method=$GraphMethod"
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    $ShardStatus = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
        Log "Found prior completion marker; re-running index with preserved input/cache"
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
    $ShardStatus["#method"]    = $GraphMethod
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
        Write-Host '& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1" -SkipConvert' -ForegroundColor Green
        Write-Host ""
        Write-Host "This will skip convert and restart the index using the existing input/output folders." -ForegroundColor Gray
        Write-Host "LLM response cache is preserved, so previously completed requests can be reused during recomputation." -ForegroundColor Gray
        Write-Host ""
    }
}

Log "=== run_finance_analysis.ps1 started ==="
Log "Source=$Source  Target=$Target  Method=$GraphMethod  Model=$Model"
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
} elseif (Test-Path $ConvertDoneFile) {
    $Done = Get-Content $ConvertDoneFile -Raw | ConvertFrom-Json
    Log "Skipping convert — already completed at $($Done.timestamp) (delete $ConvertDoneFile to force re-convert)"
} else {
    Invoke-ConvertStep
}

if ($SkipIndex) {
    Log "Skipping index (-SkipIndex flag set)"
} else {
    Wait-Ollama
    Confirm-OllamaModelsInstalled -ModelNames @($Model, $EmbeddingModel)
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
