#!/usr/bin/env bash
# Run the upstream smoke inside the existing server02 Isaac image.
set -euo pipefail
root=/data/ykj_robodojo/embodiedevo-comparison-20261029
base=/data/ykj_robodojo/RoboLaya
gpu=${1:-0}
run=${2:?Supply a fresh timestamp-prefixed run directory}
[[ "$gpu" =~ ^[01]$ ]] || exit 2
mkdir -p "$root/.cache/"{home,xdg,runtime,tmp,torch}
exec docker run --rm --gpus "device=$gpu" --network host --ipc private --shm-size=1g \
  --user 0:0 --mount "type=bind,src=$root,dst=$root" \
  --mount "type=bind,src=$base,dst=$base,readonly" --workdir "$root" \
  --env ACCEPT_EULA=Y --env OMNI_KIT_ACCEPT_EULA=YES \
  --env NVIDIA_DRIVER_CAPABILITIES=all --env CUDA_VISIBLE_DEVICES=0 \
  --env "HOME=$root/.cache/home" --env "TMPDIR=$root/.cache/tmp" \
  --env "XDG_CACHE_HOME=$root/.cache/xdg" --env "XDG_RUNTIME_DIR=$root/.cache/runtime" \
  --env "TORCH_EXTENSIONS_DIR=$root/.cache/torch" --env PYTHONDONTWRITEBYTECODE=1 \
  --env SETUPTOOLS_SCM_PRETEND_VERSION=0.0.post1.dev100 \
  --entrypoint /bin/bash nvcr.io/nvidia/isaac-sim:5.1.0 -lc '
    export CARB_APP_PATH=/isaac-sim/kit ISAAC_PATH=/isaac-sim EXP_PATH=/isaac-sim/apps
    source /isaac-sim/setup_python_env.sh
    export LD_LIBRARY_PATH=/data/ykj_robodojo/RoboLaya/.conda/lib:$LD_LIBRARY_PATH
    export LD_PRELOAD=/isaac-sim/kit/libcarb.so
    export PYTHONPATH="$PWD:$PWD/vendor/robodojo:$PWD/vendor/robodojo/XPolicyLab:$PWD/vendor/robodojo/third_party/curobo:$PYTHONPATH"
    for source in "$PWD"/vendor/robodojo/third_party/IsaacLab/source/*; do
      if [ -d "$source" ]; then export PYTHONPATH="$source:$PYTHONPATH"; fi
    done
    exec /data/ykj_robodojo/RoboLaya/.conda/bin/python -c '\''import os,sys; from orchestrator import resources; original=resources.sim_env; resources.sim_env=lambda *a,**k: dict(original(*a,**k),XDG_RUNTIME_DIR=os.environ["XDG_RUNTIME_DIR"]); from scripts.smoke_robodojo import main; sys.exit(main())'\'' --worker --gpu 0 --env-task play_tic_tac_toe --run-dir "$1"
  ' bash "$run"
