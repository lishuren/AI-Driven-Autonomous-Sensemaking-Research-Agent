# Run the legacy .NET C# maintenance sensemaking agent.
# Can be invoked from any location:
#   & "<path>\topicexample\run.ps1"

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentDir   = Join-Path $ScriptDir "..\sensemaking-agent"
$AgentDir   = (Resolve-Path $AgentDir).Path

Push-Location $AgentDir
try {
    python -m sensemaking_agent `
        --topic-dir $ScriptDir `
        --max-iterations 4 `
        --log-level INFO
} finally {
    Pop-Location
}
