#!/usr/bin/env bash
# Run server02's existing Isaac Sim image with a per-campaign writable cache.
set -euo pipefail

project_root="$(realpath "${ROBO_PROJECT_ROOT:?Set ROBO_PROJECT_ROOT to the RoboLaya checkout}")"
cache_root="$(realpath -m "${ISAAC_JOB_CACHE:?Set ISAAC_JOB_CACHE inside the RoboLaya checkout}")"
case "$cache_root/" in
  "$project_root/"*) ;;
  *) echo "ISAAC_JOB_CACHE must be on the RoboLaya project mount" >&2; exit 2 ;;
esac
[[ -d "$project_root/robodojo" && -x "$project_root/.conda/bin/python" ]] || {
  echo "RoboLaya checkout or its project Python is unavailable" >&2
  exit 2
}
gpu="${CUDA_VISIBLE_DEVICES:-0}"
[[ "$gpu" =~ ^[0-9]+$ ]] || { echo "One GPU index is required" >&2; exit 2; }
mkdir -p "$cache_root/container-home" "$cache_root/tmp" \
  "$cache_root/xdg" "$cache_root/torch-extensions"

exec docker run --rm --gpus "device=$gpu" --network host --ipc private --shm-size=1g \
  --user 0:0 \
  --mount "type=bind,src=$project_root,dst=$project_root" \
  --workdir "$PWD" \
  --env ACCEPT_EULA=Y --env OMNI_KIT_ACCEPT_EULA=YES \
  --env NVIDIA_DRIVER_CAPABILITIES=all \
  --env PROJECT_ROOT="$project_root" \
  --env HOME="$cache_root/container-home" \
  --env TMPDIR="$cache_root/tmp" \
  --env XDG_CACHE_HOME="$cache_root/xdg" \
  --env TORCH_EXTENSIONS_DIR="$cache_root/torch-extensions" \
  --env EXTERNAL_PYTHONPATH="${PYTHONPATH:-}" \
  --env SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NVIDIA_CUROBO=0.0.post1.dev100 \
  --env SETUPTOOLS_SCM_PRETEND_VERSION=0.0.post1.dev100 \
  --env CUDA_VISIBLE_DEVICES=0 \
  --env COMPANY_OBSERVATION --env COMPANY_LAYOUT_SHA256 --env COMPANY_LAYOUT_PATH \
  --env COMPANY_ORACLE_GEOMETRY --env EXPERT_SKIP_RESET_CAPTURE \
  --env EXPERT_STATE_ONLY_CAPTURE --env EXPERT_TRAINING_STEP_LIMIT \
  --env EXPERT_PROJECT_ROOT --env HF_HUB_OFFLINE --env TRANSFORMERS_OFFLINE \
  --env PYTHONNOUSERSITE \
  --entrypoint /bin/bash nvcr.io/nvidia/isaac-sim:5.1.0 \
  -lc 'export CARB_APP_PATH=/isaac-sim/kit ISAAC_PATH=/isaac-sim EXP_PATH=/isaac-sim/apps;
       source /isaac-sim/setup_python_env.sh;
       export PYTHONPATH="$EXTERNAL_PYTHONPATH:$PYTHONPATH";
       for source in "$PROJECT_ROOT"/robodojo/third_party/IsaacLab/source/*; do
         if [ -d "$source" ]; then export PYTHONPATH="$source:$PYTHONPATH"; fi;
       done;
       export PYTHONPATH="$PROJECT_ROOT/robodojo/third_party/curobo:$PYTHONPATH";
       export LD_LIBRARY_PATH="$PROJECT_ROOT/.conda/lib:$LD_LIBRARY_PATH";
       export LD_PRELOAD=/isaac-sim/kit/libcarb.so;
       exec "$PROJECT_ROOT/.conda/bin/python" "$@"' python "$@"
