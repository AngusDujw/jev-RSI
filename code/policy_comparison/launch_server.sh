#!/usr/bin/env bash
set -euo pipefail
GPU=$1
TASK=$2
RUN=$3
PORT=$4
CAMPAIGN=/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018
NATIVE=/home/user/ykj/project/RoboLaya
[[ "$GPU" =~ ^[01]$ && "$TASK" =~ ^(stack_blocks|classify_objects)$ ]]
[[ "$RUN" == "$CAMPAIGN/"* ]]
mkdir -p "$RUN/sim" "$RUN/cache/home" "$RUN/cache/tmp" "$RUN/cache/xdg" "$RUN/cache/torch" "$CAMPAIGN/shared-extension-cache"
exec docker run --rm --name "policy-20261018-${TASK}-${PORT}" \
  --gpus "device=$GPU" --network host --ipc private --shm-size=1g \
  --user 0:0 \
  --mount "type=bind,src=$NATIVE,dst=$NATIVE,readonly" \
  --mount type=bind,src=/data/ykj_robodojo/RoboLaya,dst=/data/ykj_robodojo/RoboLaya,readonly \
  --mount "type=bind,src=$CAMPAIGN,dst=$CAMPAIGN" \
  --workdir "$NATIVE/robodojo" \
  --env ACCEPT_EULA=Y --env OMNI_KIT_ACCEPT_EULA=YES --env PRIVACY_CONSENT=Y \
  --env NVIDIA_DRIVER_CAPABILITIES=all --env CUDA_VISIBLE_DEVICES=0 \
  --env "HOME=$RUN/cache/home" --env "TMPDIR=$RUN/cache/tmp" \
  --env "XDG_CACHE_HOME=$RUN/cache/xdg" --env "TORCH_EXTENSIONS_DIR=$RUN/cache/torch" \
  --env OMP_NUM_THREADS=1 --env MKL_NUM_THREADS=1 --env OPENBLAS_NUM_THREADS=1 \
  --env PYTHONNOUSERSITE=1 \
  --env SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NVIDIA_CUROBO=0.0.post1.dev100 \
  --entrypoint /bin/bash nvcr.io/nvidia/isaac-sim:5.1.0 \
  -c 'set -eo pipefail
    export CARB_APP_PATH=/isaac-sim/kit ISAAC_PATH=/isaac-sim EXP_PATH=/isaac-sim/apps
    source /isaac-sim/setup_python_env.sh
    export PYTHONPATH="$1/official_runtime:$2/robodojo:$2/robodojo/XPolicyLab:$PYTHONPATH"
    for directory in "$2"/robodojo/third_party/IsaacLab/source/*; do
      [[ ! -d "$directory" ]] || export PYTHONPATH="$directory:$PYTHONPATH"
    done
    export PYTHONPATH="$2/robodojo/third_party/curobo:$PYTHONPATH"
    export LD_LIBRARY_PATH="$2/.conda/lib:$LD_LIBRARY_PATH"
    export LD_PRELOAD=/isaac-sim/kit/libcarb.so
    campaign=$1; native=$2; shift 2
    exec "$native/.conda/bin/python" -u "$campaign/server_entry.py" "$@"
  ' launch "$CAMPAIGN" "$NATIVE" --task "$TASK" --eval-seed 0 \
  --output "$RUN/sim" --port "$PORT" --headless --enable_cameras --device cuda:0 \
  --kit_args="--/exts/omni.kit.registry.nucleus/cachePath=$CAMPAIGN/shared-extension-cache --/renderer/activeGpu=0 --/renderer/multiGpu/enabled=false --/app/updateOrder/checkForHydraRenderComplete=1000 --/app/renderer/waitIdle=true --/app/hydraEngine/waitIdle=true"
