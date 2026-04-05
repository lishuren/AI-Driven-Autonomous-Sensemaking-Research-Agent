# Index local resources into a GraphRAG knowledge graph.
# Run this BEFORE run.ps1 whenever you add or change files in resources/.
#
#   & "<path>\topicexample\prepare.ps1"

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResourcesDir = Join-Path $ScriptDir "resources"
$GraphRAGDir  = Join-Path $ScriptDir "graphrag"

if (-not (Test-Path $ResourcesDir)) {
    Write-Error "Resources directory not found: $ResourcesDir"
    exit 1
}

# Ensure the graphrag output directory exists.
if (-not (Test-Path $GraphRAGDir)) {
    New-Item -ItemType Directory -Path $GraphRAGDir | Out-Null
}

Write-Host "Indexing resources into GraphRAG..."
Write-Host "  Source:  $ResourcesDir"
Write-Host "  Target:  $GraphRAGDir"
Write-Host ""

graphragloader index `
    --source $ResourcesDir `
    --target $GraphRAGDir `
    --include-code

Write-Host ""
Write-Host "Done.  You can now run the sensemaking agent with run.ps1"
