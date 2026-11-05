#!/usr/bin/env bash
# Project-local environments; upstream's LIBERO-PRO installer owns simulator pins.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
UPSTREAM=$ROOT/baseline/HexaShell-runtime
REV=e0190ddb757955131578e9f9071f4ee8e7113f7a
BOOTSTRAP_PY=${BOOTSTRAP_PY:-$ROOT/.venv-libero-plus/bin/python}
export TMPDIR=$ROOT/code/runs/hexashell-setup/tmp
export UV_CACHE_DIR=$ROOT/.cache/hexashell-uv
export UV_PYTHON_INSTALL_DIR=$ROOT/.tools/hexashell-python
export PIP_CACHE_DIR=$ROOT/.cache/hexashell-pip
export HF_HUB_CACHE=$ROOT/.cache/hexashell-hf
mkdir -p "$TMPDIR" "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$ROOT/.tools"
if ! test -x "$ROOT/.tools/uv/bin/uv"; then
  "$BOOTSTRAP_PY" -m pip install --target "$ROOT/.tools/uv" uv
fi
UV=$ROOT/.tools/uv/bin/uv
if ! test -d "$UPSTREAM/.git"; then
  git clone --depth 1 --filter=blob:none https://github.com/HexaFuture/HexaShell.git "$UPSTREAM"
fi
if test "$(git -C "$UPSTREAM" rev-parse HEAD)" != "$REV"; then
  test -z "$(git -C "$UPSTREAM" status --porcelain)" || { echo 'Upstream checkout is dirty'; exit 1; }
  git -C "$UPSTREAM" fetch --depth 1 origin "$REV"
  git -C "$UPSTREAM" checkout --detach "$REV"
fi
"$UV" venv --python 3.11 --seed --allow-existing "$ROOT/.venv-hexashell"
"$UV" pip install --python "$ROOT/.venv-hexashell/bin/python" -r "$UPSTREAM/requirements.txt"
"$UV" venv --python 3.11 --seed --allow-existing "$ROOT/.venv-libero-pro"
BASE_PY=$ROOT/.venv-libero-pro/bin/python VENV=$ROOT/.venv-libero-pro \
  DATA_DIR=$ROOT/code/outputs/hexashell/libero-pro \
  bash "$UPSTREAM/scripts/setup/setup_libero.sh"

# SAM3 runs separately under its officially required Python >=3.12.
"$UV" venv --python 3.12 --seed --allow-existing "$ROOT/.venv-hexashell-sam3"
SAM_PY=$ROOT/.venv-hexashell-sam3/bin/python
"$UV" pip install --python "$SAM_PY" torch==2.7.0 torchvision==0.22.0 \
  --index-url https://download.pytorch.org/whl/cu128
if ! test -d "$ROOT/baseline/sam3/.git"; then
  git clone --depth 1 https://github.com/facebookresearch/sam3.git "$ROOT/baseline/sam3"
fi
"$UV" pip install --python "$SAM_PY" -e "$ROOT/baseline/sam3" \
  'setuptools<81' einops pycocotools psutil opencv-python-headless pillow
mkdir -p "$ROOT/code/checkpoints/hexashell"
"$SAM_PY" -c 'from huggingface_hub import hf_hub_download; import sys; print(hf_hub_download("facebook/sam3", "sam3.pt", local_dir=sys.argv[1]))' \
  "$ROOT/code/checkpoints/hexashell"
"$SAM_PY" -m pip freeze > "$ROOT/code/runs/hexashell-setup/sam3-freeze.txt"
"$ROOT/.venv-hexashell/bin/python" -m pip freeze > "$ROOT/code/runs/hexashell-setup/policy-freeze.txt"
git -C "$ROOT/baseline/sam3" rev-parse HEAD > "$ROOT/code/runs/hexashell-setup/sam3-revision.txt"
echo 'Project-local policy, simulator and SAM3 environments ready.'
