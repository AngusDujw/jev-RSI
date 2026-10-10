#!/usr/bin/env bash
# Run this project's RGB-D bridge in server02's existing Isaac Sim 5.1 image.
set -euo pipefail

jev_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
robolaya_root=/home/user/ykj/project/RoboLaya
gpu="${CUDA_VISIBLE_DEVICES:-0}"
[[ "$gpu" =~ ^[0-9]+$ ]] || { echo "One GPU index is required" >&2; exit 2; }
mkdir -p "$robolaya_root/.cache/container-home" "$robolaya_root/.cache/tmp" \
  "$robolaya_root/.cache/xdg" "$robolaya_root/.cache/torch-extensions"

exec docker run --rm --gpus "device=$gpu" --network host --ipc host \
  --user 0:0 \
  --mount "type=bind,src=$robolaya_root,dst=$robolaya_root" \
  --mount "type=bind,src=$jev_root,dst=$jev_root" \
  --workdir "$PWD" \
  --env ACCEPT_EULA=Y --env OMNI_KIT_ACCEPT_EULA=YES \
  --env NVIDIA_DRIVER_CAPABILITIES=all \
  --env PROJECT_ROOT="$robolaya_root" \
  --env HOME="$robolaya_root/.cache/container-home" \
  --env EXTERNAL_PYTHONPATH="${PYTHONPATH:-}" \
  --env SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NVIDIA_CUROBO=0.0.post1.dev100 \
  --env SETUPTOOLS_SCM_PRETEND_VERSION=0.0.post1.dev100 \
  --env CUDA_VISIBLE_DEVICES=0 \
  --env COMPANY_OBSERVATION --env COMPANY_LAYOUT_SHA256 --env COMPANY_LAYOUT_PATH \
  --env COMPANY_ORACLE_GEOMETRY --env EXPERT_SKIP_RESET_CAPTURE \
  --env EXPERT_STATE_ONLY_CAPTURE --env EXPERT_TRAINING_STEP_LIMIT \
  --env EXPERT_PROJECT_ROOT --env HF_HUB_OFFLINE --env TRANSFORMERS_OFFLINE \
  --env PYTHONNOUSERSITE --env TMPDIR --env XDG_CACHE_HOME \
  --env TORCH_EXTENSIONS_DIR \
  --entrypoint /bin/bash nvcr.io/nvidia/isaac-sim:5.1.0 \
  -lc 'export CARB_APP_PATH=/isaac-sim/kit ISAAC_PATH=/isaac-sim EXP_PATH=/isaac-sim/apps;
       source /isaac-sim/setup_python_env.sh;
       export PYTHONPATH="$EXTERNAL_PYTHONPATH:$PYTHONPATH";
       export LD_LIBRARY_PATH="$PROJECT_ROOT/.conda/lib:$LD_LIBRARY_PATH";
       export LD_PRELOAD=/isaac-sim/kit/libcarb.so;
       exec "$PROJECT_ROOT/.conda/bin/python" "$@"' python "$@"
