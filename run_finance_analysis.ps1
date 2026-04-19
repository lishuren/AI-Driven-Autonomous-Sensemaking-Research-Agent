<#
.SYNOPSIS
    Two-step GraphRAG workflow for D:\Finance:
    1. Convert source files into GraphRAG input text with a controllable char cap
    2. Run GraphRAG indexing on the prepared project
    Reports are generated separately on demand via graphragloader query.

.USAGE
    *** RE-RUN AFTER CRASH / INTERRUPTION: pass NO flags. Ever. ***
    The script auto-detects what is already done and skips it automatically.

    # Normal run — first time or any restart:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1"

    # Status check only (no workflow steps executed):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_finance_analysis.ps1" -CheckShardStatus

    AUTO-SKIP RULES (handled internally — you do nothing):
      Convert : skipped when .convert_done.json exists and input/ has files
      Index   : skipped when .shard_status.json marks it complete AND output/ has parquet files

    FORCE A STEP TO RE-RUN (delete its marker, then plain re-run):
      Re-convert : Remove-Item "D:\FinanceRAG\.convert_done.json"
      Re-index   : Remove-Item "D:\FinanceRAG\.shard_status.json"; Remove-Item "D:\FinanceRAG\output" -Recurse

    EMERGENCY SKIP FLAGS (-SkipConvert, -SkipIndex) EXIST BUT SHOULD NEVER BE NEEDED.
    If you think you need one, delete the relevant marker instead and plain re-run.
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
    # Triggers model loading via a background generate job, then polls /api/ps
    # to detect when Ollama has the model in memory.  This avoids blocking on
    # inference itself, which can exceed any timeout on CPU-heavy configs.
    param(
        [string]$ModelName,
        [int]$TimeoutSeconds = 3600,
        [int]$PollIntervalSeconds = 60
    )
    $PsUrl     = "$OllamaBaseUrl/api/ps"
    $WarmupUrl = "$OllamaBaseUrl/api/generate"
    $Deadline  = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Warming up model: $ModelName (timeout=$TimeoutSeconds s)..."

    # Fire a generate in the background to trigger Ollama to load the model.
    # keep_alive=30m prevents it from unloading before the indexer starts.
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
            try {
                $Ps = Invoke-RestMethod -Uri $PsUrl -Method Get -TimeoutSec 10 -ErrorAction Stop
                $Loaded = @($Ps.models | Where-Object { $_.name -like "$ModelName*" -and $_.size -gt 0 })
                if ($Loaded.Count -gt 0) {
                    Log "Model loaded: $ModelName  ($([math]::Round($Loaded[0].size / 1GB, 1)) GB in memory)"
                    return
                }
            } catch {}

            # Fallback: some Ollama builds lag in /api/ps reporting. If a tiny
            # direct generate succeeds, the model is ready for indexing.
            try {
                $ProbeBody = @{ model = $ModelName; prompt = "ping"; stream = $false; options = @{ num_predict = 1 }; keep_alive = "30m" } | ConvertTo-Json -Depth 5
                $Probe = Invoke-RestMethod -Uri $WarmupUrl -Method Post -ContentType "application/json" -Body $ProbeBody -TimeoutSec 120 -ErrorAction Stop
                if ($null -ne $Probe) {
                    Log "Model ready via generate probe: $ModelName"
                    return
                }
            } catch {
                if (Test-OllamaMissingModelError $_) {
                    throw "Model is missing from Ollama: $ModelName. Install it with: ollama pull $ModelName"
                }
            }

            $Remaining = [Math]::Max(0, [int]($Deadline - (Get-Date)).TotalSeconds)
            if ($Remaining -le 0) { break }
            $SleepSeconds = [Math]::Min($PollIntervalSeconds, $Remaining)
            Log "Model not loaded yet ($ModelName), retrying in $SleepSeconds s... ($Remaining s remaining)"
            Start-Sleep -Seconds $SleepSeconds
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
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking embedding model readiness: $ModelName (timeout=$TimeoutSeconds s)..."

    while ((Get-Date) -lt $Deadline) {
        try {
            $BodyObj = @{ model = $ModelName; input = @("ping") }
            $Body = $BodyObj | ConvertTo-Json -Depth 5

            try {
                $Resp = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/embed" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
                if ($null -ne $Resp -and $Resp.embeddings -and ($Resp.embeddings.Count -gt 0)) { Log "Embedding model ready via /api/embed: $ModelName"; return }
            } catch {
                # ignore and try /api/embeddings
            }

            try {
                $Resp2 = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/embeddings" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
                if ($null -ne $Resp2) {
                    if ((($Resp2.embedding -ne $null) -and ($Resp2.embedding.Count -gt 0)) -or (($Resp2.embeddings -ne $null) -and ($Resp2.embeddings.Count -gt 0))) {
                        Log "Embedding model ready via /api/embeddings: $ModelName"; return
                    }
                }
            } catch {
                if (Test-OllamaMissingModelError $_) { throw "Embedding model is missing from Ollama: $ModelName. Install it with: ollama pull $ModelName" }
            }
        } catch {
            if (Test-OllamaMissingModelError $_) { throw "Embedding model is missing from Ollama: $ModelName. Install it with: ollama pull $ModelName" }
        }

        $Remaining = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Embedding model not ready yet ($ModelName), retrying in $PollIntervalSeconds s... ($Remaining s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    throw "Embedding model did not become ready within $TimeoutSeconds seconds: $ModelName"
}

function Update-SettingsEmbedText {
    param([string]$SettingsPath)
    if (-not (Test-Path $SettingsPath)) { return }

    $Content = Get-Content -Path $SettingsPath -Raw
    if ($Content -match '\bembed_text\s*:') {
        $Updated = $false
        $New = [regex]::Replace($Content, '(?m)^(\s+batch_max_tokens:)\s*\d+', "`${1} 2000")
        if ($New -ne $Content) { $Content = $New; $Updated = $true }
        $New = [regex]::Replace($Content, '(?m)^(\s+batch_size:)\s*\d+', "`${1} 8")
        if ($New -ne $Content) { $Content = $New; $Updated = $true }
        if ($Updated) {
            Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
            Log "Updated settings.yaml embed_text: batch_size=8, batch_max_tokens=2000"
        } else {
            Log "settings.yaml embed_text already configured correctly"
        }
    } else {
        $Block = "`r`n" + "embed_text:`r`n" + "  batch_size: 8`r`n" + "  batch_max_tokens: 2000`r`n"
        Add-Content -Path $SettingsPath -Value $Block -Encoding UTF8
        Log "Added embed_text section to settings.yaml: batch_size=8, batch_max_tokens=2000"
    }
}

function Initialize-Settings {
    $SettingsPath = Join-Path $Target "settings.yaml"
    if (Test-Path $SettingsPath) {
        Log "settings.yaml already exists"
    } else {
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
    Update-SettingsTimeouts  -SettingsPath $SettingsPath
    Update-SettingsEmbedText -SettingsPath $SettingsPath
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

    $New = [regex]::Replace(
        $Content,
        '(default_completion_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)(?:\s{4}timeout:\s*\d+\r?\n)?(?:\s{4}call_args:\r?\n\s{6}timeout:\s*\d+\r?\n)?',
        "`$1    call_args:`r`n      timeout: $RequestTimeout`r`n",
        [System.Text.RegularExpressions.RegexOptions]::Multiline
    )
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    $New = [regex]::Replace(
        $Content,
        '(default_embedding_model:\r?\n(?:\s{4}.+\r?\n)*?\s{4}api_key:\s*ollama\r?\n)(?:\s{4}timeout:\s*\d+\r?\n)?(?:\s{4}call_args:\r?\n\s{6}timeout:\s*\d+\r?\n)?',
        "`$1    call_args:`r`n      timeout: $RequestTimeout`r`n",
        [System.Text.RegularExpressions.RegexOptions]::Multiline
    )
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    if ($Updated) {
        Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
        Log "Updated settings.yaml with call_args.timeout=$RequestTimeout for Ollama models"
    }
}

function Invoke-ConvertStep {
    Log "Step 1/3 Convert started  max_chars=$ConvertMaxChars"
    $ConvertArgs = @(
        "convert",
        "--source",          $Source,
        "--target",          $Target,
        "--include-code",
        "--max-chars",       $ConvertMaxChars,
        "--ocr-lang",        "chi_sim+eng"
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
        Log "Found prior shard status — will resume from last completed workflow checkpoint"
    }
    $IndexArgs = @(
        "index",
        "--root",   $Target,
        "--method", $GraphMethod
    )
    $StartTime = Get-Date
    Log "Running GraphRAG index..."
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GraphRAG index failed with exit code $LASTEXITCODE"
    }
    $Elapsed = (Get-Date) - $StartTime
    $ShardStatus["#completed"]   = $true
    $ShardStatus["#timestamp"]   = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus["#method"]      = $GraphMethod
    $ShardStatus["#model"]       = $Model
    $ShardStatus["#elapsed_min"] = [math]::Round($Elapsed.TotalMinutes, 1)
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
    Write-Host "========== RESUMPTION GUIDE ==========" -ForegroundColor Cyan
    if ($Status) {
        Write-Host "Last index run  : $($Status.'#timestamp')" -ForegroundColor Yellow
        if ($Status.'#method') { Write-Host "Index method    : $($Status.'#method')" -ForegroundColor Gray }
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
    Write-Host "  Convert  : skipped when marker is valid; otherwise runs incremental convert"  -ForegroundColor Green
    Write-Host "  Index    : skipped automatically when already complete; re-runs ALL workflows from scratch otherwise (LLM cache makes it fast)" -ForegroundColor Green
    Write-Host ""
    Write-Host "TO START FRESH (delete marker files):" -ForegroundColor White
    Write-Host "  Re-convert : Remove-Item '$ConvertDoneFile'" -ForegroundColor Gray
    Write-Host "  Re-index   : Remove-Item '$Target\.shard_status.json'; Remove-Item '$Target\output' -Recurse" -ForegroundColor Gray
    Write-Host "=============================================" -ForegroundColor DarkGray
    Write-Host ""
}

# Point Tesseract at the user tessdata directory (contains chi_sim)
$env:TESSDATA_PREFIX = "$env:USERPROFILE\tessdata"

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

$InputDir = Join-Path $Target "input"
$InputHasFiles = (Test-Path $InputDir) -and (Get-ChildItem $InputDir -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
$ConvertProgressFile = Join-Path $Target ".convert_progress"

if ($SkipConvert) {
    Log "Skipping convert (-SkipConvert flag set)"
} elseif (Test-Path $ConvertDoneFile) {
    # .convert_done.json takes priority over .convert_progress — completion wins.
    if (-not $InputHasFiles) {
        Log "Convert marker exists but $InputDir has no files — running convert to rebuild input."
        Invoke-ConvertStep
    } else {
        $DoneTimestamp = "unknown"
        try {
            $Done = Get-Content $ConvertDoneFile -Raw | ConvertFrom-Json
            if ($Done -and $Done.timestamp) { $DoneTimestamp = [string]$Done.timestamp }
        } catch {}
        Log "Skipping convert — already completed at $DoneTimestamp (delete $ConvertDoneFile to force re-convert)"
    }
} elseif (Test-Path $ConvertProgressFile) {
    Log "Detected $ConvertProgressFile — prior convert appears incomplete. Running incremental convert to resume."
    Invoke-ConvertStep
} else {
    Invoke-ConvertStep
}

$_OutputDir = Join-Path $Target "output"
$_OutputHasParquet = (Test-Path $_OutputDir) -and (Get-ChildItem $_OutputDir -Recurse -Filter "*.parquet" -ErrorAction SilentlyContinue | Select-Object -First 1)

$IndexAlreadyDone = $false
$_shardStatus = Get-ShardStatus
if ($_shardStatus -and $_shardStatus.'#completed' -eq $true) {
    if ($_OutputHasParquet) {
        $IndexAlreadyDone = $true
    } else {
        Log "Index marker says completed but output parquet files are missing — clearing marker and re-indexing."
        Remove-Item (Join-Path $Target ".shard_status.json") -Force -ErrorAction SilentlyContinue
    }
}

if ($SkipIndex -or $IndexAlreadyDone) {
    if ($IndexAlreadyDone) {
        Log "Skipping index — already completed at $($_shardStatus.'#timestamp') (delete $Target\.shard_status.json and $Target\output to re-index)"
    } else {
        Log "Skipping index (-SkipIndex flag set)"
    }
} else {
    Wait-Ollama
    Confirm-OllamaModelsInstalled -ModelNames @($Model, $EmbeddingModel)
    Wait-OllamaModel -ModelName $Model
    Wait-OllamaEmbedding -ModelName $EmbeddingModel
    Invoke-IndexStep
}

Log "=== All done. Index complete. Run queries on demand with: graphragloader query --target $Target --method global --question '<your question>' ==="
Write-Host "Index ready: $Target" -ForegroundColor Green
Show-ResumptionGuide
