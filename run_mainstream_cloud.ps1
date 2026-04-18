<#
.SYNOPSIS
    Cloud-model variant of run_mainstream_fast.ps1 using gemma4:31b-cloud.

    Reuses D:\mainstreamGraphRAG so all prior convert output and partially-completed
    index workflows are preserved.  GraphRAG 3.x auto-skips workflows whose output
    parquet files already exist, so only incomplete steps (e.g. create_community_reports_text)
    will actually run.  The ~2,593/8,324 community reports already cached from the local
    run will be replayed instantly.

    Key differences from the fast script:
      - Model          : gemma4:31b-cloud (Ollama-proxied cloud) for both index and reports
      - No dual-model  : cloud is fast enough for everything
      - Pre-flight     : checks cloud model accessibility and quota before starting work
      - Resilient      : just re-run after any crash — no flags needed

.USAGE
    *** RE-RUN AFTER CRASH / INTERRUPTION: pass NO flags. Ever. ***
    The script auto-detects what is already done and skips it automatically.

    # Normal run — first time or any restart:
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_cloud.ps1"

    # Status check only (no workflow steps executed):
    & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_cloud.ps1" -CheckShardStatus

    AUTO-SKIP RULES (handled internally — you do nothing):
      Convert : skipped when .convert_done.json exists and input/ has files
      Index   : skipped when .shard_status.json marks it complete AND output/ has parquet files
      Reports : skipped individually when the .md file already exists

    FORCE A STEP TO RE-RUN (delete its marker, then plain re-run):
      Re-convert : Remove-Item "D:\mainstreamGraphRAG\.convert_done.json"
      Re-index   : Remove-Item "D:\mainstreamGraphRAG\.shard_status.json"; Remove-Item "D:\mainstreamGraphRAG\output" -Recurse
      Re-report  : Remove-Item "D:\mainstreamGraphRAG\reports\<name>.md"

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

$env:DISABLE_AIOHTTP_TRANSPORT    = "True"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"

# ── Paths ────────────────────────────────────────────────────────────────────
$LoaderExe   = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe"
$GraphRagExe = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe"
$PythonExe   = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\python.exe"
$Source      = "D:\Mainstream"
$Target      = "D:\mainstreamGraphRAG"
$ReportsDir  = Join-Path $Target "reports"
$LogFile     = Join-Path $Target "run_mainstream_cloud.log"
$ConvertDoneFile = Join-Path $Target ".convert_done.json"

# ── CLOUD-MODE SETTINGS ─────────────────────────────────────────────────────
$Provider       = "ollama"
$Model          = "gemma4:31b-cloud"
$EmbeddingModel = "nomic-embed-text"
$QueryMethod    = "global"
$RequestTimeout = 1800
$ConvertMaxChars = 100000
$GraphMethod    = "fast"
$FastChunkSize    = 2000
$FastChunkOverlap = 150
$OllamaBaseUrl  = "http://localhost:11434"

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
    New-Item -ItemType Directory -Force -Path $Target     | Out-Null
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
    # Cloud models (e.g. gemma4:31b-cloud) are not listed in /api/tags — skip local check for them.
    $LocalModels = @($ModelNames | Where-Object { $_ -notmatch '-cloud$' })
    if ($LocalModels.Count -eq 0) {
        Log "All models are cloud models — skipping local install check: $($ModelNames -join ', ')"
        return
    }
    $Installed = @(Get-OllamaInstalledModels)
    $Missing   = @($LocalModels | Where-Object { -not (Test-OllamaModelInstalled -ModelName $_ -InstalledModels $Installed) })
    if ($Missing.Count -gt 0) {
        $Cmds = ($Missing | ForEach-Object { "ollama pull $_" }) -join "; "
        throw "Required Ollama model(s) not installed: $($Missing -join ', '). Install them first: $Cmds"
    }
    Log "Verified Ollama models are installed: $($LocalModels -join ', ')"
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
    foreach ($Msg in ($Candidates | Where-Object { $null -ne $_ -and $_ -ne '' })) {
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
    param([string]$ModelName, [int]$TimeoutSeconds = 3600, [int]$PollIntervalSeconds = 60)

    # Cloud models run remotely — skip /api/ps polling, just verify reachability.
    if ($ModelName -match '-cloud$') {
        Log "Cloud model detected ($ModelName) — verifying reachability via test generate..."
        $WarmupUrl  = "$OllamaBaseUrl/api/generate"
        $WarmupBody = @{
            model   = $ModelName
            prompt  = "hello"
            stream  = $false
            options = @{ num_predict = 1 }
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

    $WarmupBody = @{ model = $ModelName; prompt = "hello"; stream = $false; options = @{ num_predict = 1 }; keep_alive = "30m" } | ConvertTo-Json -Depth 5
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

            $Rem = [Math]::Max(0, [int]($Deadline - (Get-Date)).TotalSeconds)
            if ($Rem -le 0) { break }
            $SleepSeconds = [Math]::Min($PollIntervalSeconds, $Rem)
            Log "Model not loaded yet ($ModelName), retrying in $SleepSeconds s... ($Rem s remaining)"
            Start-Sleep -Seconds $SleepSeconds
        }
        throw "Model did not load within $TimeoutSeconds s: $ModelName"
    } finally {
        $WarmupJob | Stop-Job -PassThru | Remove-Job -Force -ErrorAction SilentlyContinue
    }
}

function Wait-OllamaEmbedding {
    param([string]$ModelName, [int]$TimeoutSeconds = 600, [int]$PollIntervalSeconds = 15)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Log "Checking embedding model readiness: $ModelName (timeout=$TimeoutSeconds s)..."
    while ((Get-Date) -lt $Deadline) {
        try {
            # Use the 'input' payload and try both common embedding endpoints.
            $BodyObj = @{ model = $ModelName; input = @("ping") }
            $Body = $BodyObj | ConvertTo-Json -Depth 5

            # 1) Try /api/embed (some Ollama/litellm versions use this and return 'embeddings')
            try {
                $Resp = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/embed" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
                if ($null -ne $Resp -and $Resp.embeddings -and ($Resp.embeddings.Count -gt 0)) { Log "Embedding model ready via /api/embed: $ModelName"; return }
            } catch {
                # ignore and try the other endpoint below
            }

            # 2) Try /api/embeddings (older/newer shapes may provide 'embedding' or 'embeddings')
            try {
                $Resp2 = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/embeddings" -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 90 -ErrorAction Stop
                if ($null -ne $Resp2) {
                    if ((($Resp2.embedding -ne $null) -and ($Resp2.embedding.Count -gt 0)) -or (($Resp2.embeddings -ne $null) -and ($Resp2.embeddings.Count -gt 0))) {
                        Log "Embedding model ready via /api/embeddings: $ModelName"; return
                    }
                }
            } catch {
                if (Test-OllamaMissingModelError $_) { throw "Embedding model missing: $ModelName. Run: ollama pull $ModelName" }
            }
        } catch {
            if (Test-OllamaMissingModelError $_) { throw "Embedding model missing: $ModelName. Run: ollama pull $ModelName" }
        }

        $Rem = [int]($Deadline - (Get-Date)).TotalSeconds
        Log "Embedding model not ready ($ModelName), retrying in $PollIntervalSeconds s... ($Rem s remaining)"
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Embedding model did not become ready within $TimeoutSeconds s: $ModelName"
}

# Swaps the completion model name inside settings.yaml.
function Update-SettingsModel {
    param([string]$SettingsPath, [string]$ModelName)
    if (-not (Test-Path $SettingsPath)) { return }

    $Lines = Get-Content -LiteralPath $SettingsPath -Encoding UTF8
    $InBlock = $false
    $Patched = $false

    $NewLines = foreach ($Line in $Lines) {
        if ($Line -match '^\s+default_completion_model:') { $InBlock = $true }
        elseif ($InBlock -and $Line -match '^[^ \t]' -and $Line.Trim() -ne '') { $InBlock = $false }

        if ($InBlock -and -not $Patched -and $Line -match '^(\s+model:)\s*\S+') {
            $Line = $Matches[1] + " $ModelName"
            $Patched = $true
        }
        $Line
    }

    if ($Patched) {
        $NewLines | Set-Content -LiteralPath $SettingsPath -Encoding UTF8
        Log "settings.yaml: completion model set to $ModelName"
    } else {
        Log "settings.yaml: 'model:' key not found in default_completion_model block -- check settings.yaml" "WARN"
    }
}

function Update-SettingsChunking {
    param([string]$SettingsPath)
    if (-not (Test-Path $SettingsPath)) { return }

    $Content = Get-Content -Path $SettingsPath -Raw
    $Updated = $false

    $New = [regex]::Replace($Content, '(?m)^(\s+size:)\s*\d+', "`${1} $FastChunkSize")
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    $New = [regex]::Replace($Content, '(?m)^(\s+overlap:)\s*\d+', "`${1} $FastChunkOverlap")
    if ($New -ne $Content) { $Content = $New; $Updated = $true }

    if ($Updated) {
        Set-Content -Path $SettingsPath -Value $Content -Encoding UTF8 -NoNewline
        Log "Updated settings.yaml: chunk_size=$FastChunkSize, chunk_overlap=$FastChunkOverlap"
    }
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

function Update-SettingsTimeouts {
    param([string]$SettingsPath)
    if (-not (Test-Path $SettingsPath)) { return }

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

function Initialize-Settings {
    $SettingsPath = Join-Path $Target "settings.yaml"
    if (Test-Path $SettingsPath) {
        Log "settings.yaml already exists"
    } else {
        Log "Generating settings.yaml (model: $Model)"
        $InitArgs = @(
            "init",
            "--target",          $Target,
            "--provider",        $Provider,
            "--model",           $Model,
            "--embedding-model", $EmbeddingModel,
            "--request-timeout", $RequestTimeout
        )
        & $LoaderExe @InitArgs
        if ($LASTEXITCODE -ne 0) { throw "Failed to generate settings.yaml" }
    }
    Update-SettingsTimeouts  -SettingsPath $SettingsPath
    Update-SettingsChunking  -SettingsPath $SettingsPath
    Update-SettingsEmbedText -SettingsPath $SettingsPath
    # Ensure settings.yaml reflects the cloud model
    Update-SettingsModel     -SettingsPath $SettingsPath -ModelName $Model
}

function Test-CloudModelAccessible {
    param([string]$ModelName)

    if ($ModelName -notmatch '-cloud$') { return }

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

        if ($Msg -match 'quota|rate.?limit|daily.?limit|limit.?exceeded|too.?many.?request|429') {
            Log "DAILY QUOTA REACHED for $ModelName — stopping now. Re-run tomorrow." "WARN"
            Log "Server response: $Msg" "WARN"
            Write-Host ""
            Write-Host "============================================================" -ForegroundColor Yellow
            Write-Host "  Cloud model daily quota reached: $ModelName" -ForegroundColor Yellow
            Write-Host "  No work was started." -ForegroundColor Yellow
            Write-Host "  Re-run the script tomorrow — it will resume automatically." -ForegroundColor Yellow
            Write-Host "============================================================" -ForegroundColor Yellow
            Write-Host ""
            exit 0
        }

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

function Invoke-ConvertStep {
    Log "Step 1/3 Convert started  max_chars=$ConvertMaxChars (cloud mode)"
    $ConvertArgs = @(
        "convert",
        "--source",    $Source,
        "--target",    $Target,
        "--include-code",
        "--max-chars", $ConvertMaxChars
    )
    & $LoaderExe @ConvertArgs
    if ($LASTEXITCODE -ne 0) { throw "Convert failed with exit code $LASTEXITCODE" }
    @{ completed = $true; timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); source = $Source; max_chars = $ConvertMaxChars } |
        ConvertTo-Json | Set-Content $ConvertDoneFile -Encoding UTF8
    Log "Convert complete."
}

function Invoke-IndexStep {
    Log "Step 2/3 GraphRAG index started  method=$GraphMethod (cloud mode)  model=$Model"
    $ShardStatusFile = Join-Path $Target ".shard_status.json"
    $ShardStatus     = @{}
    if (Test-Path $ShardStatusFile) {
        $ShardStatus = Get-Content $ShardStatusFile -Raw | ConvertFrom-Json -AsHashtable
        Log "Found prior shard status — GraphRAG will auto-skip workflows with existing output parquets"
    }
    Log "Ensuring NLTK data packages are available..."
    & $PythonExe -c @"
import nltk, sys
pkg_paths = {
    'punkt':                          'tokenizers/punkt',
    'punkt_tab':                      'tokenizers/punkt_tab',
    'averaged_perceptron_tagger':     'taggers/averaged_perceptron_tagger',
    'averaged_perceptron_tagger_eng': 'taggers/averaged_perceptron_tagger_eng',
    'maxent_ne_chunker':              'chunkers/maxent_ne_chunker',
    'maxent_ne_chunker_tab':          'chunkers/maxent_ne_chunker_tab',
    'words':                          'corpora/words',
    'stopwords':                      'corpora/stopwords',
    'brown':                          'corpora/brown',
}
missing = []
for pkg, path in pkg_paths.items():
    try:
        nltk.data.find(path)
    except LookupError:
        missing.append(pkg)
for pkg in missing:
    try:
        nltk.download(pkg, quiet=True)
    except Exception as e:
        print(f'Warning: could not download NLTK package {pkg}: {e}', file=sys.stderr)
"@ 2>&1 | Out-Null

    $IndexArgs = @("index", "--root", $Target, "--method", $GraphMethod)
    $StartTime = Get-Date
    Log "Running GraphRAG index (cloud)..."
    & $GraphRagExe @IndexArgs
    if ($LASTEXITCODE -ne 0) { throw "GraphRAG index failed with exit code $LASTEXITCODE" }
    $Elapsed = (Get-Date) - $StartTime
    $ShardStatus["#completed"]   = $true
    $ShardStatus["#timestamp"]   = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $ShardStatus["#method"]      = $GraphMethod
    $ShardStatus["#model"]       = $Model
    $ShardStatus["#elapsed_min"] = [math]::Round($Elapsed.TotalMinutes, 1)
    $ShardStatus | ConvertTo-Json | Set-Content $ShardStatusFile -Encoding UTF8
    Log "GraphRAG index complete. Elapsed: $([math]::Round($Elapsed.TotalHours, 2)) h  ($Model)"
}

function Invoke-ReportStep {
    param(
        [string]$Name,
        [string]$Question,
        [string]$Method = $QueryMethod,
        [string]$ResponseType = "Detailed Report"
    )
    $OutFile = Join-Path $ReportsDir ($Name + ".md")
    if (Test-Path $OutFile) {
        Log "Skipping report — already exists: $Name  (delete $OutFile to regenerate)"
        return
    }
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
    $Header = "# $Name`n`n> Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (cloud mode)`n`n"
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
    Write-Host ""
    Write-Host "========== RESUMPTION GUIDE [cloud] ==========" -ForegroundColor Cyan
    if ($Status) {
        Write-Host "Last index run  : $($Status.'#timestamp')" -ForegroundColor Yellow
        if ($Status.'#method')      { Write-Host "Index method    : $($Status.'#method')"       -ForegroundColor Gray }
        if ($Status.'#model')       { Write-Host "Model           : $($Status.'#model')"        -ForegroundColor Gray }
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
    Write-Host "  Convert  : skipped when marker is valid; otherwise runs incremental convert"  -ForegroundColor Green
    Write-Host "  Index    : skipped automatically when already complete; GraphRAG skips workflows with existing output parquets" -ForegroundColor Green
    Write-Host "  Reports  : skipped individually when the .md file already exists" -ForegroundColor Green
    Write-Host ""
    Write-Host "TO START FRESH (delete marker files):" -ForegroundColor White
    Write-Host "  Re-convert : Remove-Item '$ConvertDoneFile'" -ForegroundColor Gray
    Write-Host "  Re-index   : Remove-Item '$Target\.shard_status.json'; Remove-Item '$Target\output' -Recurse" -ForegroundColor Gray
    Write-Host "  Re-report  : Remove-Item '$ReportsDir\<name>.md'" -ForegroundColor Gray
    Write-Host "================================================" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Entry point ───────────────────────────────────────────────────────────────
Log "=== run_mainstream_cloud.ps1 started ==="
Log "CLOUD MODE: model=$Model  method=$GraphMethod  chunk_size=$FastChunkSize"
Log "DISABLE_AIOHTTP_TRANSPORT=$($env:DISABLE_AIOHTTP_TRANSPORT)"
Log "LITELLM_LOCAL_MODEL_COST_MAP=$($env:LITELLM_LOCAL_MODEL_COST_MAP)"

if ($CheckShardStatus) {
    Show-ResumptionGuide
    exit 0
}

Test-Prerequisite
Initialize-Settings

# Ensure Ollama API is up (needed for local embedding model)
Wait-Ollama

# Pre-flight: check cloud model accessibility before any long-running steps
Test-CloudModelAccessible -ModelName $Model
Confirm-OllamaModelsInstalled -ModelNames @($Model, $EmbeddingModel)
Wait-OllamaEmbedding -ModelName $EmbeddingModel

$InputDir = Join-Path $Target "input"
$InputHasFiles = (Test-Path $InputDir) -and (Get-ChildItem $InputDir -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
$ConvertProgressFile = Join-Path $Target ".convert_progress"

if ($SkipConvert) {
    Log "Skipping convert (-SkipConvert flag set)"
} elseif (Test-Path $ConvertDoneFile) {
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
    Invoke-IndexStep
}

# ── Reports ───────────────────────────────────────────────────────────────────
$Reports = @(
    @{ Name = "analysis_report";         Question = "Provide a comprehensive analysis of this corpus: major themes, key findings, key entities and their relationships, uncertainties, and actionable conclusions. Include supporting evidence for each finding." },
    @{ Name = "system_structure_report";  Question = "Describe the overall system structure: identify the core components and subsystems, their individual responsibilities, the interfaces and contracts between them, dependency relationships, and how the components collaborate to deliver end-to-end functionality." },
    @{ Name = "business_analysis_report"; Question = "Provide a business analysis: identify business objectives and stakeholders, map value drivers and revenue/cost levers, assess risks and opportunities, highlight strategic constraints, and provide recommendations with supporting evidence from the corpus." },
    @{ Name = "flow_analysis_report";     Question = "Provide a flow analysis: describe end-to-end process flows and control flows, identify key decision points and branching logic, highlight bottlenecks or failure points, and suggest optimisations backed by evidence from the corpus." },
    @{ Name = "data_flow_report";         Question = "Provide a data flow analysis: identify all data sources and ingestion paths, describe transformations and enrichment steps, map storage layers and data lineage, highlight data quality risks or gaps, and list governance and compliance checkpoints found in the corpus." }
)

foreach ($r in $Reports) {
    Invoke-ReportStep -Name $r.Name -Question $r.Question
}

Log "=== All done (cloud mode). Reports saved to: $ReportsDir ==="
Write-Host "Reports folder: $ReportsDir" -ForegroundColor Green
Show-ResumptionGuide
