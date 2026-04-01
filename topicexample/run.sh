#!/usr/bin/env bash
# Run the legacy .NET C# maintenance sensemaking agent.
# Can be invoked from any location:
#   /path/to/topicexample/run.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/../sensemaking-agent" && pwd)"

cd "$AGENT_DIR"

python -m sensemaking_agent \
  --topic-dir "$SCRIPT_DIR" \
  --max-iterations 4 \
  --log-level INFO
