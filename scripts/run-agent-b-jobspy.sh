#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/jobspy-mcp-server"
JOBSPY_DOCKER_DIR="$SERVER_DIR/jobspy"
HOST="${JOBSPY_HOST:-127.0.0.1}"
PORT="${JOBSPY_PORT:-9423}"
HEALTH_URL="http://$HOST:$PORT/health"
LOG_DIR="$ROOT_DIR/private/logs"
LOG_FILE="$LOG_DIR/jobspy-mcp.log"
PID_FILE="$ROOT_DIR/private/run_locks/jobspy-mcp.pid"
MAX_RESULTS="${JOBSPY_AGENT_B_MAX_RESULTS:-3}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/run-agent-b-jobspy.sh [--max-results N] [additional agent_b_run args]

Environment:
  JOBSPY_AGENT_B_MAX_RESULTS  Default max results if --max-results is not passed.
  JOBSPY_AUTOBUILD=1          Build the local Docker image if it is missing.

Before first use:
  scripts/setup-jobspy-image.sh

The script starts the local JobSpy MCP server if needed, then runs:
  python3 -m app.discovery.agent_b_run --sources jobspy_mcp_candidate
USAGE
}

AGENT_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --max-results)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --max-results" >&2
        exit 2
      fi
      MAX_RESULTS="$2"
      shift 2
      ;;
    *)
      AGENT_ARGS+=("$1")
      shift
      ;;
  esac
done

health_ok() {
  curl --silent --fail --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_command curl
require_command npm
require_command python3

if [[ ! -d "$SERVER_DIR" ]]; then
  echo "missing JobSpy MCP server directory: $SERVER_DIR" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"

if ! docker image inspect jobspy >/dev/null 2>&1; then
  if [[ "${JOBSPY_AUTOBUILD:-0}" == "1" ]]; then
    echo "Building missing Docker image: jobspy"
    docker build -t jobspy "$JOBSPY_DOCKER_DIR"
  else
    cat >&2 <<EOF
Docker image 'jobspy' is missing.
Run this once:
  scripts/setup-jobspy-image.sh

Or allow this script to build it:
  JOBSPY_AUTOBUILD=1 scripts/run-agent-b-jobspy.sh
EOF
    exit 1
  fi
fi

if health_ok; then
  echo "JobSpy MCP server is already running at $HEALTH_URL"
else
  echo "Starting JobSpy MCP server at $HEALTH_URL"
  (
    cd "$SERVER_DIR"
    JOBSPY_HOST="$HOST" JOBSPY_PORT="$PORT" ENABLE_SSE=1 npm start
  ) >"$LOG_FILE" 2>&1 &
  echo "$!" >"$PID_FILE"

  for _ in {1..30}; do
    if health_ok; then
      break
    fi
    sleep 1
  done

  if ! health_ok; then
    echo "JobSpy MCP server did not become healthy. Recent log output:" >&2
    tail -n 80 "$LOG_FILE" >&2 || true
    exit 1
  fi
fi

cd "$ROOT_DIR"
python3 -m app.discovery.agent_b_run \
  --sources jobspy_mcp_candidate \
  --max-results "$MAX_RESULTS" \
  "${AGENT_ARGS[@]}"
