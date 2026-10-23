#!/usr/bin/env bash
# Foreground continuation only; preserve the original batch and its successful episode.
set -euo pipefail
ROBOICL_PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$ROBOICL_PROJECT_ROOT"
export ROBOICL_KIT_EXTENSION_PATH="$ROBOICL_PROJECT_ROOT/.runtime/speed-kit-slot0/data/Kit/Isaac-Sim/5.1/exts/3"
export PYTHONFAULTHANDLER=1
exec .venv-policy/bin/python -B reproduction/speed_experiment.py \
  --output results/speed-stack-bowls-20261023-reboot \
  --sim-python "$ROBOICL_PROJECT_ROOT/.venv-sim/bin/python" \
  --policy-python "$ROBOICL_PROJECT_ROOT/.venv-policy/bin/python" \
  --parallel 2 --minimum-free-mib 7500 --minimum-available-ram-mib 7500 \
  --case default_h5:0 --case fast_h5:1 --case default_h5:1 \
  --case default_h1:0 --case fast_h1:0 --case default_h1:1 --case fast_h1:1 \
  "$@"
