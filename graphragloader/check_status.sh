#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: check_status.sh [TARGET_DIR]

Check whether a GraphRAG indexing job is currently running and inspect the
state of a GraphRAG project directory.

Arguments:
  TARGET_DIR   GraphRAG project root containing settings.yaml, input/, and
               output/. Defaults to the current working directory.

Examples:
  ./check_status.sh /data/my-graphrag
  ./check_status.sh ../topicexample/graphrag
EOF
}

resolve_path() {
    local path="$1"

    if [ -d "$path" ]; then
        (
            cd "$path"
            pwd -P
        )
        return 0
    fi

    case "$path" in
        /*) printf '%s\n' "$path" ;;
        *) printf '%s/%s\n' "$(pwd -P)" "$path" ;;
    esac
}

is_windows_posix_shell() {
    case "$(uname -s 2>/dev/null || true)" in
        MINGW*|MSYS*|CYGWIN*) return 0 ;;
        *) return 1 ;;
    esac
}

to_windows_path() {
    local path="$1"
    local drive
    local rest

    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$path" 2>/dev/null && return 0
    fi

    case "$path" in
        /[a-zA-Z]/*)
            drive="${path#/}"
            drive="${drive%%/*}"
            rest="${path#/$drive/}"
            rest="${rest//\//\\}"
            printf '%s:\\%s\n' "$(printf '%s' "$drive" | tr '[:lower:]' '[:upper:]')" "$rest"
            ;;
        *)
            printf '%s\n' "$path"
            ;;
    esac
}

list_processes_windows() {
    local powershell_cmd

    read -r -d '' powershell_cmd <<'EOF' || true
$pattern = 'graphragloader|python(?:\.exe)?\s+.*-m\s+graphrag\s+index|graphrag(?:\.exe)?\s+index'
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } |
  ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.CommandLine }
EOF

    if command -v powershell.exe >/dev/null 2>&1; then
        powershell.exe -NoProfile -Command "$powershell_cmd" | tr -d '\r' || true
        return 0
    fi

    if command -v pwsh.exe >/dev/null 2>&1; then
        pwsh.exe -NoProfile -Command "$powershell_cmd" | tr -d '\r' || true
        return 0
    fi

    if command -v pwsh >/dev/null 2>&1; then
        pwsh -NoProfile -Command "$powershell_cmd" | tr -d '\r' || true
    fi
}

list_processes() {
    if is_windows_posix_shell; then
        list_processes_windows
    elif command -v pgrep >/dev/null 2>&1; then
        pgrep -af 'graphragloader|python.*-m graphrag index|graphrag index' || true
    else
        ps ax -o pid=,etime=,command= |
            grep -E 'graphragloader|python.*-m graphrag index|graphrag index' |
            grep -v 'grep -E' || true
    fi
}

filter_matching_processes() {
    local processes="$1"
    shift
    local pattern

    if [ -z "$processes" ]; then
        return 0
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        for pattern in "$@"; do
            [ -z "$pattern" ] && continue
            if [[ "$line" == *"$pattern"* ]]; then
                printf '%s\n' "$line"
                break
            fi
        done
    done <<< "$processes"
}

append_match_pattern() {
    local value="$1"
    if [ -n "$value" ]; then
        MATCH_PATTERNS+=("$value")
    fi
}
    
count_files() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        printf '0\n'
        return 0
    fi

    find "$dir" -type f 2>/dev/null | wc -l | awk '{print $1}'
}

latest_file() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        return 0
    fi

    find "$dir" -type f -exec ls -1t {} + 2>/dev/null | head -n 1 || true
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

TARGET_INPUT="${1:-.}"
TARGET_DIR="$(resolve_path "$TARGET_INPUT")"
TARGET_DIR_WIN="$(to_windows_path "$TARGET_DIR")"
TARGET_NAME="$(basename "$TARGET_DIR")"

MATCH_PATTERNS=()
append_match_pattern "$TARGET_DIR"
append_match_pattern "$TARGET_DIR_WIN"
append_match_pattern "$TARGET_INPUT"
if [ "$TARGET_INPUT" != "." ] && [ "$TARGET_INPUT" != "./" ]; then
    append_match_pattern "$(to_windows_path "$TARGET_INPUT")"
fi
append_match_pattern "/$TARGET_NAME"
append_match_pattern "\\$TARGET_NAME"

if [ ! -d "$TARGET_DIR" ]; then
    echo "Target directory not found: $TARGET_DIR" >&2
    exit 1
fi

INPUT_DIR="$TARGET_DIR/input"
OUTPUT_DIR="$TARGET_DIR/output"
STATE_FILE="$TARGET_DIR/.graphragloader_state.json"
SETTINGS_FILE="$TARGET_DIR/settings.yaml"

ALL_PROCESSES="$(list_processes)"
MATCHING_PROCESSES="$(filter_matching_processes "$ALL_PROCESSES" "${MATCH_PATTERNS[@]}")"

INPUT_COUNT="$(count_files "$INPUT_DIR")"
OUTPUT_COUNT="$(count_files "$OUTPUT_DIR")"
LATEST_OUTPUT="$(latest_file "$OUTPUT_DIR")"

STATUS="NOT_INITIALIZED"
if [ -n "$MATCHING_PROCESSES" ]; then
    STATUS="RUNNING"
elif [ "$OUTPUT_COUNT" -gt 0 ]; then
    STATUS="IDLE_WITH_OUTPUT"
elif [ "$INPUT_COUNT" -gt 0 ]; then
    STATUS="READY_TO_INDEX"
elif [ -f "$SETTINGS_FILE" ] || [ -f "$STATE_FILE" ]; then
    STATUS="INITIALIZED"
fi

echo "GraphRAG Status"
echo "==============="
echo "Target:            $TARGET_DIR"
echo "Status:            $STATUS"
echo "Settings present:  $( [ -f "$SETTINGS_FILE" ] && echo yes || echo no )"
echo "State file:        $( [ -f "$STATE_FILE" ] && echo yes || echo no )"
echo "Input files:       $INPUT_COUNT"
echo "Output files:      $OUTPUT_COUNT"

if [ -n "$LATEST_OUTPUT" ]; then
    echo "Latest output:     $LATEST_OUTPUT"
fi

echo ""
if [ -n "$MATCHING_PROCESSES" ]; then
    echo "Active processes for this target:"
    printf '%s\n' "$MATCHING_PROCESSES"
elif [ -n "$ALL_PROCESSES" ]; then
    echo "Active GraphRAG processes (other targets or unspecified target path):"
    printf '%s\n' "$ALL_PROCESSES"
else
    echo "Active GraphRAG processes: none"
fi