#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOBSPY_DOCKER_DIR="$ROOT_DIR/jobspy-mcp-server/jobspy"

if ! command -v docker >/dev/null 2>&1; then
  echo "missing required command: docker" >&2
  exit 1
fi

if [[ ! -f "$JOBSPY_DOCKER_DIR/Dockerfile" ]]; then
  echo "missing JobSpy Dockerfile: $JOBSPY_DOCKER_DIR/Dockerfile" >&2
  exit 1
fi

docker build -t jobspy "$JOBSPY_DOCKER_DIR"
