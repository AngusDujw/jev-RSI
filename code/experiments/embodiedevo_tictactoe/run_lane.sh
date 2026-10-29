#!/usr/bin/env bash
set -euo pipefail
root=/data/ykj_robodojo/embodiedevo-comparison-20261029
base=/data/ykj_robodojo/RoboLaya
lane=${1:?baseline or jev}
run=${2:?fresh YYYYMMDDHHMM-prefixed run directory}
case "$lane" in baseline) gpu=0; task=RoboDojo;; jev) gpu=1; task=RoboDojoJev;; *) exit 2;; esac
cache="$root/.cache/$lane"
mkdir -p "$cache"/{home,xdg,runtime,torch,kit-cache,kit-logs,kit-data,var-tmp} "$root/.t$gpu"
exec docker run --rm --name "embodiedevo-orchestrator-$lane-20261029" \
  --gpus "device=$gpu" --network host --ipc private --shm-size=1g --user 0:0 \
  --mount "type=bind,src=$root,dst=$root" \
  --mount "type=bind,src=$base,dst=$base,readonly" \
  --mount "type=bind,src=$cache/kit-cache,dst=/isaac-sim/kit/cache" \
  --mount "type=bind,src=$cache/kit-logs,dst=/isaac-sim/kit/logs" \
  --mount "type=bind,src=$cache/kit-data,dst=/isaac-sim/kit/data" \
  --mount "type=bind,src=$cache/var-tmp,dst=/var/tmp" \
  --mount type=bind,src=/usr/bin/docker,dst=/usr/local/bin/docker,readonly \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --workdir "$root" --env ACCEPT_EULA=Y --env OMNI_KIT_ACCEPT_EULA=YES \
  --env NVIDIA_DRIVER_CAPABILITIES=all --env CUDA_VISIBLE_DEVICES=0 \
  --env "HOME=$cache/home" --env "TMPDIR=$root/.t$gpu" \
  --env "XDG_CACHE_HOME=$cache/xdg" --env "XDG_RUNTIME_DIR=$cache/runtime" \
  --env "TORCH_EXTENSIONS_DIR=$cache/torch" --env PYTHONDONTWRITEBYTECODE=1 \
  --env "EMBODIEDEVO_CODEX_HOME=$root/.cache/transport-home" \
  --env "JEV_ROUTER_URL=${JEV_ROUTER_URL:-http://172.18.0.1:7934/route}" \
  --env "EMBODIEDEVO_RUN_ID=$run" \
  --env SETUPTOOLS_SCM_PRETEND_VERSION=0.0.post1.dev100 \
  --env EMBODIEDEVO_SIMULATOR_STARTUP_TIMEOUT=1800 \
  --entrypoint /bin/bash nvcr.io/nvidia/isaac-sim:5.1.0 -lc '
    export CARB_APP_PATH=/isaac-sim/kit ISAAC_PATH=/isaac-sim EXP_PATH=/isaac-sim/apps
    source /isaac-sim/setup_python_env.sh
    export LD_LIBRARY_PATH=/data/ykj_robodojo/RoboLaya/.conda/lib:$LD_LIBRARY_PATH
    export PATH="$PWD/.cache/bin:$PATH"
    export LD_PRELOAD=/isaac-sim/kit/libcarb.so
    export PYTHONPATH="$PWD:$PWD/vendor/robodojo:$PWD/vendor/robodojo/XPolicyLab:$PWD/vendor/robodojo/third_party/curobo:$PYTHONPATH"
    for source in "$PWD"/vendor/robodojo/third_party/IsaacLab/source/*; do
      if [ -d "$source" ]; then export PYTHONPATH="$source:$PYTHONPATH"; fi
    done
    exec /data/ykj_robodojo/RoboLaya/.conda/bin/python -u .cache/deployment/run_original.py --repo "$PWD" --task "$1" --run-dir "$2"
  ' bash "$task" "$run"
