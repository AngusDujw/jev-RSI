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
python3 -c '
import pathlib,sys,subprocess,hashlib,json,shutil
project,run=map(pathlib.Path,sys.argv[1:])
snapshot=run/"framework_source"
snapshot.mkdir(exist_ok=False)
records=[]
sources=list((project/"code/planner_advancer").glob("*.py"))+list((project/"code/planner_advancer").glob("*.sh"))+list((project/"code/contracts").glob("*.md"))
for source in sources:
    relative=source.relative_to(project)
    target=snapshot/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    records.append(dict(path=str(relative),sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
revision=subprocess.check_output(["git","-C",str(project),"rev-parse","HEAD"],text=True).strip()
(snapshot/"manifest.json").write_text(json.dumps(dict(commit=revision,files=records,note="Exact launch-time source copies; hashes capture any uncommitted changes. No credentials or experience files are copied."),indent=2))
' "$PROJECT" "$RUN"
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
if [[ "${ROBO_TOOL_GEOMETRY_DETAILS:-0}" == 1 ]]; then
  PROCESSING_ARGS+=(--tool-geometry-details)
fi
exec /root/miniconda3/envs/isaacsim5.1/bin/python -u "$PROJECT/code/planner_advancer/runtime.py" \
  --task "$TASK" --layout "$LAYOUT" --output "$RUN/episode" --headless --enable_cameras \
  "${LAYOUT_ARGS[@]}" \
  "${PROCESSING_ARGS[@]}" \
  --camera-intrinsics "${ROBO_CAMERA_INTRINSICS:-native}" \
  --kit_args "--/renderer/activeGpu=$GPU --/renderer/multiGpu/enabled=false --/app/renderer/resolution/width=640 --/app/renderer/resolution/height=480"
