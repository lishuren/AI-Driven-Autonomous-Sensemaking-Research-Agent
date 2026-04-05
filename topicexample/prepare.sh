#!/usr/bin/env bash
# Index local resources into a GraphRAG knowledge graph.
# Run this BEFORE run.sh whenever you add or change files in resources/.
#
#   /path/to/topicexample/prepare.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOURCES_DIR="$SCRIPT_DIR/resources"
GRAPHRAG_DIR="$SCRIPT_DIR/graphrag"

if [ ! -d "$RESOURCES_DIR" ]; then
    echo "Resources directory not found: $RESOURCES_DIR" >&2
    exit 1
fi

# Ensure the graphrag output directory exists.
mkdir -p "$GRAPHRAG_DIR"

echo "Indexing resources into GraphRAG..."
echo "  Source:  $RESOURCES_DIR"
echo "  Target:  $GRAPHRAG_DIR"
echo ""

graphragloader index \
    --source "$RESOURCES_DIR" \
    --target "$GRAPHRAG_DIR" \
    --include-code

echo ""
echo "Done.  You can now run the sensemaking agent with run.sh"
