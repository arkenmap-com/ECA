#!/usr/bin/env bash
set -euo pipefail

docker run --rm -it --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  burnp3-console \
  mono "$SYNCROSIM_HOME/SyncroSim.Console.exe" "$@"
