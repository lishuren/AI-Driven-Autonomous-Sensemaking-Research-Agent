<#
.SYNOPSIS
Check whether a GraphRAG indexing job is currently running and inspect a GraphRAG project directory.

.PARAMETER TargetDir
GraphRAG project root containing settings.yaml, input/, and output/. Defaults to the current directory.

.EXAMPLE
./check_status.ps1 D:\mainstreamGraphRAG

.EXAMPLE
./check_status.ps1 ..\topicexample\graphrag
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$TargetDir = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-TargetPath {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

function Get-GraphRAGProcesses {
    # Match any process whose command line contains a graphrag or graphragloader invocation.
    # Use a loose pattern to handle quoted executables, e.g. "graphrag.exe" index ...
    $pattern = 'graphragloader|graphrag(?:\.exe)?["\s].*?\b(?:index|convert|query|init|update)\b'

    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } |
        ForEach-Object {
            [pscustomobject]@{
                ProcessId   = $_.ProcessId
                Name        = $_.Name
                CommandLine = $_.CommandLine
            }
        }
}

function Get-MatchPatterns {
    param(
        [string]$ResolvedPath,
        [string]$RawPath
    )

    $patterns = New-Object System.Collections.Generic.List[string]
    $trimmedPath = $ResolvedPath.TrimEnd([char[]]@([char]'\', [char]'/'))
    $targetName = [System.IO.Path]::GetFileName($trimmedPath)

    $patterns.Add($ResolvedPath)
    $patterns.Add(($ResolvedPath -replace '\\', '/'))

    if ($RawPath -and $RawPath -notin @('.', '.\\', './')) {
        $patterns.Add($RawPath)
        $patterns.Add(($RawPath -replace '/', '\\'))
        $patterns.Add(($RawPath -replace '\\', '/'))
    }

    if ($targetName) {
        $patterns.Add("\\$targetName")
        $patterns.Add("/$targetName")
    }

    return $patterns | Where-Object { $_ } | Select-Object -Unique
}

function Parse-GraphRAGArgs {
    param([string]$CommandLine)

    $result = [pscustomobject]@{ Operation = ''; Root = ''; Source = ''; Target = ''; Method = '' }

    if ($CommandLine -match '(?:graphrag|graphragloader)(?:loader)?(?:\.exe)?\b[^|&]*?\b(index|convert|query|init|update)\b') {
        $result.Operation = $Matches[1]
    }

    foreach ($entry in @(
        @{ Prop = 'Root';   Flag = '--root'   },
        @{ Prop = 'Source'; Flag = '--source' },
        @{ Prop = 'Target'; Flag = '--target' },
        @{ Prop = 'Method'; Flag = '--method' }
    )) {
        $flag = $entry.Flag
        if ($CommandLine -match "$flag\s+(?:\""([^\""]+)\""|([^\s]+))") {
            $result.$($entry.Prop) = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        }
    }

    return $result
}

function Get-FilteredProcesses {
    param(
        [object[]]$Processes,
        [string]$ResolvedTarget
    )

    $normalTarget = $ResolvedTarget.TrimEnd([char]'\', [char]'/')

    $Processes | Where-Object {
        $a = Parse-GraphRAGArgs -CommandLine $_.CommandLine
        $processRoot = if ($a.Root) { $a.Root } elseif ($a.Target) { $a.Target } else { '' }
        return $processRoot.TrimEnd([char]'\', [char]'/') -ieq $normalTarget
    }
}

function Get-FileCount {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return 0
    }

    return (Get-ChildItem -LiteralPath $Path -File -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
}

function Get-LatestFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $null
    }

    return Get-ChildItem -LiteralPath $Path -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

$resolvedTarget = Resolve-TargetPath -Path $TargetDir
if (-not (Test-Path -LiteralPath $resolvedTarget -PathType Container)) {
    throw "Target directory not found: $resolvedTarget"
}

$inputDir = Join-Path $resolvedTarget "input"
$outputDir = Join-Path $resolvedTarget "output"
$stateFile = Join-Path $resolvedTarget ".graphragloader_state.json"
$settingsFile = Join-Path $resolvedTarget "settings.yaml"

$allProcesses = @(Get-GraphRAGProcesses)
$matchingProcesses = @(Get-FilteredProcesses -Processes $allProcesses -ResolvedTarget $resolvedTarget)

$inputCount = Get-FileCount -Path $inputDir
$outputCount = Get-FileCount -Path $outputDir
$latestOutput = Get-LatestFile -Path $outputDir

$status = "NOT_INITIALIZED"
if ($matchingProcesses.Count -gt 0) {
    $status = "RUNNING"
} elseif ($outputCount -gt 0) {
    $status = "IDLE_WITH_OUTPUT"
} elseif ($inputCount -gt 0) {
    $status = "READY_TO_INDEX"
} elseif ((Test-Path -LiteralPath $settingsFile -PathType Leaf) -or (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
    $status = "INITIALIZED"
}

Write-Host "GraphRAG Status"
Write-Host "==============="
Write-Host ("Target:            {0}" -f $resolvedTarget)
Write-Host ("Status:            {0}" -f $status)
Write-Host ("Settings present:  {0}" -f $(if (Test-Path -LiteralPath $settingsFile -PathType Leaf) { 'yes' } else { 'no' }))
Write-Host ("State file:        {0}" -f $(if (Test-Path -LiteralPath $stateFile -PathType Leaf) { 'yes' } else { 'no' }))
Write-Host ("Input files:       {0}" -f $inputCount)
Write-Host ("Output files:      {0}" -f $outputCount)

if ($latestOutput) {
    Write-Host ("Latest output:     {0}" -f $latestOutput)
}

$progressFile = Join-Path $resolvedTarget ".convert_progress"
if (Test-Path -LiteralPath $progressFile -PathType Leaf) {
    try {
        $prog = Get-Content -LiteralPath $progressFile -Raw -ErrorAction Stop | ConvertFrom-Json
        $pct     = "{0:N1}" -f [double]$prog.pct
        $done    = "{0:N0}" -f [int]$prog.done
        $total   = "{0:N0}" -f [int]$prog.total
        Write-Host ("Convert progress:  {0}%  ({1} / {2} files)") -f $pct, $done, $total -ForegroundColor Cyan
        Write-Host ("Current file:      {0}" -f $prog.current) -ForegroundColor Cyan
        if ($prog.started) {
            Write-Host ("Convert started:   {0}" -f $prog.started) -ForegroundColor DarkGray
        }
    } catch {
        # progress file may be mid-write; skip silently
    }
}

Write-Host ""
if ($allProcesses.Count -gt 0) {
    Write-Host "Running GraphRAG jobs:"
    Write-Host "----------------------"
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $normalizedResolvedTarget = $resolvedTarget.TrimEnd([char]'\', [char]'/')
    foreach ($proc in $allProcesses) {
        $a = Parse-GraphRAGArgs -CommandLine $proc.CommandLine
        $jobRoot = if ($a.Root) { $a.Root } elseif ($a.Target) { $a.Target } else { '' }
        $jobKey  = "$($a.Operation)|$jobRoot|$($a.Method)"
        if (-not $seen.Add($jobKey)) { continue }  # deduplicate (launcher + python PIDs per job)

        $label = if ($a.Operation) { $a.Operation.ToUpper() } else { 'GRAPHRAG' }
        $isCurrentTarget = $jobRoot.TrimEnd([char]'\', [char]'/') -ieq $normalizedResolvedTarget
        $color = if ($isCurrentTarget) { 'Green' } else { 'Cyan' }

        $line = "  [$label]"
        if ($jobRoot)  { $line += "  $jobRoot" }
        if ($a.Method) { $line += "  (method=$($a.Method))" }
        if ($a.Source) { $line += "  <-- $($a.Source)" }
        Write-Host $line -ForegroundColor $color
    }
} else {
    Write-Host "Running GraphRAG jobs: none"
}