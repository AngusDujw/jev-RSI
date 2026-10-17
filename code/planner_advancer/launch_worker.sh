#!/usr/bin/env bash
set -euo pipefail
PROJECT=$(cd "$(dirname "$0")/../.." && pwd)
GPU=$1
TASK=$2
LAYOUT=$3
RUN=$4
NATIVE=/root/yekangjie/project/robodojo-jev
python3 "$PROJECT/code/planner_advancer/gpu_admission.py" "$GPU"
mkdir -p "$RUN/cache/tmp" "$RUN/cache/xdg" "$RUN/cache/kit"
export TMPDIR="$RUN/cache/tmp"
export XDG_CACHE_HOME="$RUN/cache/xdg"
export OMNI_KIT_ACCEPT_EULA=YES
export ACCEPT_EULA=Y
export PRIVACY_CONSENT=Y
export CUDA_VISIBLE_DEVICES="$GPU"
export PYTHONPATH="$PROJECT/.deps:$NATIVE/GPT-as-Policy:$NATIVE/robodojo:$NATIVE/robodojo/XPolicyLab:${PYTHONPATH:-}"
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
export NO_PROXY=localhost,127.0.0.1
cd "$NATIVE/robodojo"
LAYOUT_ARGS=()
PROCESSING_ARGS=()
if [[ -n "${ROBO_LAYOUT_MANIFEST:-}" ]]; then
  LAYOUT_ARGS=(--layout-manifest "$ROBO_LAYOUT_MANIFEST")
fi
if [[ "${ROBO_ENABLE_PROCESSING:-0}" == 1 ]]; then
  PROCESSING_ARGS=(--enable-processing)
fi
if [[ -n "${ROBO_PREPARED_FROM:-}" ]]; then
  PROCESSING_ARGS+=(--prepared-from "$ROBO_PREPARED_FROM")
fi
if [[ -n "${ROBO_RESUME_PROCESSING_FROM:-}" ]]; then
  PROCESSING_ARGS+=(--resume-processing-from "$ROBO_RESUME_PROCESSING_FROM")
fi
if [[ "${ROBO_DECISION_BACKEND:-luna}" == jev ]]; then
  PROCESSING_ARGS+=(--decision-backend jev)
fi
if [[ "${ROBO_OMIT_IMAGES:-0}" == 1 ]]; then
  PROCESSING_ARGS+=(--omit-images)
fi
exec /root/miniconda3/envs/isaacsim5.1/bin/python -u "$PROJECT/code/planner_advancer/runtime.py" \
  --task "$TASK" --layout "$LAYOUT" --output "$RUN/episode" --headless --enable_cameras \
  "${LAYOUT_ARGS[@]}" \
  "${PROCESSING_ARGS[@]}" \
  --kit_args "--/renderer/activeGpu=$GPU --/renderer/multiGpu/enabled=false --/app/renderer/resolution/width=640 --/app/renderer/resolution/height=480"
