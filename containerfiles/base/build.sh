#!/usr/bin/env bash
# Slim variant build — Python 3.13-slim base.
# Source of truth is ../generic/Containerfile; this script just picks
# the BASE_IMAGE arg. Run from the repo root OR from this dir; the
# script normalises cwd to the repo root before invoking podman.

set -euo pipefail

# Resolve repo root regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

IMG="${IMG:-fantastic-canvas-base:dev}"
# Match `.python-version` (3.11). Using a different minor here forces
# `uv sync --frozen` to download its own managed Python into the
# builder's `/root/.local/share/uv/python/`, which the final stage
# doesn't copy → venv shebangs break with "required file not found".
BASE_IMAGE="${BASE_IMAGE:-python:3.11-slim}"

exec podman build \
    -f containerfiles/generic/Containerfile \
    --build-arg "BASE_IMAGE=$BASE_IMAGE" \
    -t "$IMG" \
    "$@" \
    .
