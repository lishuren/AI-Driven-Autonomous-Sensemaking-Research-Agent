<#
.SYNOPSIS
    Finance GraphRAG workflow using gemma4:31b-cloud for speed comparison against run_finance_analysis.ps1 (gemma4:e4b local).
    1. Convert source files into GraphRAG input text with a controllable char cap
    2. Run GraphRAG indexing on the prepared project
    Reports are generated separately on demand via graphragloader query.

    Target directory is D:\FinanceRAG-cloud (separate from D:\FinanceRAG used by the local script)
    so both runs can co-exist without interfering.

.USAGE
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis_cloud.ps1"
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis_cloud.ps1" -SkipConvert
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis_cloud.ps1" -CheckShardStatus
    # After convert completes, a .convert_done.json marker is written to $Target.
    # Restarts automatically skip convert when this file exists.
    # Delete D:\FinanceRAG-cloud\.convert_done.json to force a full re-convert.
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
$Target      = "D:\FinanceRAG-cloud"
$LogFile     = Join-Path $Target "run_finance_analysis_cloud.log"
$ConvertDoneFile = Join-Path $Target ".convert_done.json"   # written after a successful convert; auto-skips re-convert on restart

$Provider       = "ollama"
$Model          = "gemma4:31b-cloud"
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

    # Cloud models (e.g. gemma4:31b-cloud) are not listed in /api/tags — skip local check for them.
    $LocalModels = @($ModelNames | Where-Object { $_ -notmatch '-cloud$' })
    if ($LocalModels.Count -eq 0) {
        Log "All models are cloud models — skipping local install check: $($ModelNames -join ', ')"
        return
    }

    $InstalledModels = @(Get-OllamaInstalledModels)
    $MissingModels = @()

    foreach ($ModelName in $LocalModels) {
        if (-not (Test-OllamaModelInstalled -ModelName $ModelName -InstalledModels $InstalledModels)) {
            $MissingModels += $ModelName
        }
    }

    if ($MissingModels.Count -gt 0) {
        $PullCommands = ($MissingModels | ForEach-Object { "ollama pull $_" }) -join "; "
        throw "Required Ollama model(s) not installed: $($MissingModels -join ', '). Install them first: $PullCommands"
    }

    Log "Verified Ollama models are installed: $($LocalModels -join ', ')"
}

function Test-OllamaMissingModelError {
    param($ErrorRecord)

    $candidates = @()

    if ($null -ne $ErrorRecord) {
        if ($null -ne $ErrorRecord.ErrorDetails) {
            try { $ed = $ErrorRecord.ErrorDetails.Message } catch { $ed = $null }
            if ($ed) { $candidates += $ed }
        }

        if ($null -ne $ErrorRecord.Exception) {
            try { $ex = $ErrorRecord.Exception.Message } catch { $ex = $null }
            if ($ex) { $candidates += $ex }
        }

        try { $toStr = $ErrorRecord.ToString() } catch { $toStr = $null }
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
    # For cloud models (e.g. gemma4:31b-cloud), skip the /api/ps polling — they run remotely
    # and never appear in the local process list. Just do a quick generate to confirm reachability.
    param(
        [string]$ModelName,
        [int]$TimeoutSeconds = 3600,
        [int]$PollIntervalSeconds = 60
    )

    if ($ModelName -match '-cloud$') {
        Log "Cloud model detected ($ModelName) — verifying reachability via test generate..."
        $WarmupUrl = "$OllamaBaseUrl/api/generate"
        $WarmupBody = @{
            model      = $ModelName
            prompt     = "hello"
            stream     = $false
            options    = @{ num_predict = 1 }
        } | ConvertTo-Json -Depth 5
        try {
            $Response = Invoke-RestMethod -Uri $WarmupUrl -Method Post -ContentType "application/json" -Body $WarmupBody -TimeoutSec 120 -ErrorAction Stop
            Log "Cloud model ready: $ModelName"
        } catch {
            throw "Cloud model $ModelName is not reachable. Ensure you are signed in with: ollama signin. Error: $_"
        }
        return
    }

    $PsUrl     = "$OllamaBaseUrl/api/ps"
    $WarmupUrl = "$OllamaBaseUrl/api/generate"
    $Deadline  = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Warming up model: $ModelName (timeout=$TimeoutSeconds s)..."

    $WarmupBody = @{
        model      = $ModelName
        prompt     = "hello"
        stream     = $false
        options    = @{ num_predict = 1 }
        keep_alive = "30m"
    } | ConvertTo-Json -Depth 5
    $WarmupJob = Start-Job -ScriptBlock {
        param($Url, $Body)
        try { Invoke-RestMethod -Uri $Url -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 3600 -ErrorAction SilentlyContinue } catch {}
    } -ArgumentList $WarmupUrl, $WarmupBody

    try {
        while ((Get-Date) -lt $Deadline) {
            Start-Sleep -Seconds $PollIntervalSeconds
            try {
                $Ps = Invoke-RestMethod -Uri $PsUrl -Method Get -TimeoutSec 10 -ErrorAction Stop
                $Loaded = @($Ps.models | Where-Object { $_.name -like "$ModelName*" -and $_.size -gt 0 })
                if ($Loaded.Count -gt 0) {
                    Log "Model loaded: $ModelName  ($([math]::Round($Loaded[0].size / 1GB, 1)) GB in memory)"
                    return
                }
            } catch {}
            $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
            Log "Model not loaded yet ($ModelName), retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        }
        throw "Model did not load within $TimeoutSeconds s: $ModelName"
    } finally {
        $WarmupJob | Stop-Job -PassThru | Remove-Job -Force -ErrorAction SilentlyContinue
    }
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
            $Body = @{ model = $ModelName; prompt = "ping" } | ConvertTo-Json -Depth 5
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

function Invoke-ConvertStep {
    Log "Step 1/2 Convert started  max_chars=$ConvertMaxChars"
    $ConvertArgs = @(
        "convert",
        "--source",    $Source,
        "--target",    $Target,
        "--include-code",
        "--max-chars", $ConvertMaxChars,
        "--ocr-lang",  "chi_sim+eng"
    )
    & $LoaderExe @ConvertArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Convert failed with exit code $LASTEXITCODE"
    }
    @{ completed = $true; timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); source = $Source; max_chars = $ConvertMaxChars } |
        ConvertTo-Json | Set-Content $ConvertDoneFile -Encoding UTF8
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/2 GraphRAG index started  method=$GraphMethod  model=$Model"
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    $ShardStatus = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
    }
    $IndexArgs = @(
        "index",
        "--root",   $Target,
        "--method", $GraphMethod
    )
    $OutputDir = Join-Path $Target "output"
    if ((Test-Path $OutputDir) -and (Get-ChildItem $OutputDir -Directory -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        $IndexArgs += "--resume"
        Log "Detected existing GraphRAG output artifacts — adding --resume to continue from last checkpoint"
    }
    $StartTime = Get-Date
    Log "Running GraphRAG index..."
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GraphRAG index failed with exit code $LASTEXITCODE"
    }
    $Elapsed = (Get-Date) - $StartTime
    $ShardStatus["#completed"]  = $true
    $ShardStatus["#timestamp"]  = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus["#method"]     = $GraphMethod
    $ShardStatus["#model"]      = $Model
    $ShardStatus["#elapsed_min"]= [math]::Round($Elapsed.TotalMinutes, 1)
    $ShardStatus | ConvertTo-Json | Set-Content $ShardStatusFile -Encoding UTF8
    Log "GraphRAG index complete. Elapsed: $([math]::Round($Elapsed.TotalHours, 2)) h  ($Model)"
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
    Write-Host ""
    Write-Host "========== RESUMPTION GUIDE [cloud] ==========" -ForegroundColor Cyan
    if ($Status) {
        Write-Host "Last index run  : $($Status.'#timestamp')" -ForegroundColor Yellow
        if ($Status.'#model')       { Write-Host "Model           : $($Status.'#model')"        -ForegroundColor Gray }
        if ($Status.'#method')      { Write-Host "Index method    : $($Status.'#method')"        -ForegroundColor Gray }
        if ($Status.'#elapsed_min') { Write-Host "Index duration  : $($Status.'#elapsed_min') min" -ForegroundColor Gray }
        if ($Status.'#completed') {
            Write-Host "Index status    : COMPLETE" -ForegroundColor Green
        } else {
            Write-Host "Index status    : INCOMPLETE (will resume automatically on next run)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "No prior index run detected." -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "RESUME BEHAVIOR (automatic — no flags needed):" -ForegroundColor White
    Write-Host "  Convert  : skipped automatically when .convert_done.json exists"  -ForegroundColor Green
    Write-Host "  Index    : skipped automatically when already complete; resumes from last finished workflow otherwise" -ForegroundColor Green
    Write-Host ""
    Write-Host "TO START FRESH (delete marker files):" -ForegroundColor White
    Write-Host "  Re-convert : Remove-Item '$ConvertDoneFile'" -ForegroundColor Gray
    Write-Host "  Re-index   : Remove-Item '$Target\.shard_status.json'; Remove-Item '$Target\output' -Recurse" -ForegroundColor Gray
    Write-Host "================================================" -ForegroundColor DarkGray
    Write-Host ""

    # Show elapsed time from both runs side by side if the local run also has a marker
    $LocalShard = Join-Path "D:\FinanceRAG" ".shard_status.json"
    if (Test-Path $LocalShard) {
        $Local = Get-Content $LocalShard -Raw | ConvertFrom-Json
        Write-Host "=== SPEED COMPARISON ===" -ForegroundColor Magenta
        if ($Local.'#elapsed_min')  { Write-Host "  gemma4:e4b   (local) : $($Local.'#elapsed_min') min" -ForegroundColor White }
        if ($Status -and $Status.'#elapsed_min') { Write-Host "  gemma4:31b-cloud     : $($Status.'#elapsed_min') min" -ForegroundColor White }
        Write-Host ""
    }
}

function Test-CloudModelAccessible {
    # Sends a minimal test call to the cloud model before any long-running steps.
    # Stops the script immediately if the model is unreachable or the daily quota is exhausted.
    param([string]$ModelName)

    if ($ModelName -notmatch '-cloud$') { return }  # only relevant for cloud models

    Log "Checking cloud model accessibility: $ModelName ..."
    $WarmupUrl  = "$OllamaBaseUrl/api/generate"
    $WarmupBody = @{
        model   = $ModelName
        prompt  = "hi"
        stream  = $false
        options = @{ num_predict = 1 }
    } | ConvertTo-Json -Depth 5

    try {
        $Response = Invoke-RestMethod -Uri $WarmupUrl -Method Post -ContentType "application/json" `
            -Body $WarmupBody -TimeoutSec 120 -ErrorAction Stop
        Log "Cloud model accessible: $ModelName — ready to proceed."
    } catch {
        $Msg = ''
        try { $Msg = $_.ErrorDetails.Message } catch {}
        if (-not $Msg) { try { $Msg = $_.Exception.Message } catch {} }
        if (-not $Msg) { $Msg = $_.ToString() }

        # Detect quota / rate-limit signals
        if ($Msg -match 'quota|rate.?limit|daily.?limit|limit.?exceeded|too.?many.?request|429') {
            Log "DAILY QUOTA REACHED for $ModelName — stopping now. Re-run tomorrow." "WARN"
            Log "Server response: $Msg" "WARN"
            Write-Host ""
            Write-Host "============================================================" -ForegroundColor Yellow
            Write-Host "  Cloud model daily quota reached: $ModelName" -ForegroundColor Yellow
            Write-Host "  No convert or index work was started." -ForegroundColor Yellow
            Write-Host "  Re-run the script tomorrow — it will resume automatically." -ForegroundColor Yellow
            Write-Host "============================================================" -ForegroundColor Yellow
            Write-Host ""
            exit 0
        }

        # Any other error (not signed in, network, etc.)
        Log "Cloud model $ModelName is NOT accessible — stopping. Error: $Msg" "ERROR"
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host "  Cannot reach cloud model: $ModelName" -ForegroundColor Red
        Write-Host "  Ensure you are signed in: ollama signin" -ForegroundColor Red
        Write-Host "  Error: $Msg" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host ""
        exit 1
    }
}

# Point Tesseract at the user tessdata directory (contains chi_sim)
$env:TESSDATA_PREFIX = "$env:USERPROFILE\tessdata"

Log "=== run_finance_analysis_cloud.ps1 started ==="
Log "Source=$Source  Target=$Target  Method=$GraphMethod  Model=$Model"
Log "DISABLE_AIOHTTP_TRANSPORT=$($env:DISABLE_AIOHTTP_TRANSPORT)"
Log "LITELLM_LOCAL_MODEL_COST_MAP=$($env:LITELLM_LOCAL_MODEL_COST_MAP)"

if ($CheckShardStatus) {
    Show-ResumptionGuide
    exit 0
}

Test-Prerequisite
Initialize-Settings

# Check cloud model is accessible BEFORE starting any long-running steps
# so a quota failure stops immediately rather than after hours of convert work.
Wait-Ollama
Test-CloudModelAccessible -ModelName $Model

$InputDir = Join-Path $Target "input"
$InputHasFiles = (Test-Path $InputDir) -and (Get-ChildItem $InputDir -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)

if ($SkipConvert) {
    Log "Skipping convert (-SkipConvert flag set)"
} elseif (Test-Path $ConvertDoneFile) {
    $Done = Get-Content $ConvertDoneFile -Raw | ConvertFrom-Json
    Log "Skipping convert — already completed at $($Done.timestamp) (delete $ConvertDoneFile to force re-convert)"
} elseif ($InputHasFiles) {
    Log "Skipping convert — $InputDir already contains files (copied manually). Writing completion marker."
    @{ completed = $true; timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); source = "copied from D:\FinanceRAG\input"; max_chars = $ConvertMaxChars } |
        ConvertTo-Json | Set-Content $ConvertDoneFile -Encoding UTF8
} else {
    Invoke-ConvertStep
}

$IndexAlreadyDone = $false
$_shardStatus = Get-ShardStatus
if ($_shardStatus -and $_shardStatus.'#completed' -eq $true) { $IndexAlreadyDone = $true }

if ($SkipIndex -or $IndexAlreadyDone) {
    if ($IndexAlreadyDone) {
        Log "Skipping index — already completed at $($_shardStatus.'#timestamp') (delete $Target\.shard_status.json and $Target\output to re-index)"
    } else {
        Log "Skipping index (-SkipIndex flag set)"
    }
} else {
    Confirm-OllamaModelsInstalled -ModelNames @($Model, $EmbeddingModel)
    Wait-OllamaModel -ModelName $Model
    Wait-OllamaEmbedding -ModelName $EmbeddingModel
    Invoke-IndexStep
}

Log "=== All done. Index complete. Run queries on demand with: graphragloader query --target $Target --method global --question '<your question>' ==="
Write-Host "Index ready: $Target" -ForegroundColor Green
Show-ResumptionGuide
