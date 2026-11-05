#!/usr/bin/env bash
# Run only after selecting a GPU permitted for this task. No driver changes.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
GPU=${1:-0}
PORT=${2:-18350}
OUT=${3:-$ROOT/code/runs/hexashell-services}
mkdir -p "$OUT/tmp"
export CUDA_VISIBLE_DEVICES=$GPU
export TMPDIR=$OUT/tmp
# The upstream server defaults to expandable_segments:True. vGPU can reject
# CUDA virtual-memory allocation even when ordinary tensors work. Use the
# ordinary caching allocator; this changes allocation, not model weights.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False
exec "$ROOT/.venv-hexashell-sam3/bin/python" -u \
  "$ROOT/baseline/HexaShell-runtime/services/sam3_server.py" \
  --port "$PORT" --checkpoint "$ROOT/code/checkpoints/hexashell/sam3.pt" \
  --cache-images 16 --text-cache 128 --pid-file "$OUT/sam3.pid"
