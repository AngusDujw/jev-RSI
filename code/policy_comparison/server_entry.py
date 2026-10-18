"""Load the original server without importing its unused optional cuRobo backend."""
from pathlib import Path
import sys
import types


class DisabledCuroboPlanner:
    def __init__(self, *args, **kwargs):
        raise RuntimeError('cuRobo must remain unused in the official EEF-only baseline')


from env.global_configs import ROOT_DIR
import utils
utils.__path__ = [str(Path(ROOT_DIR).resolve() / 'utils')]
import utils.load_file
module = types.ModuleType('env.planner_manager.curobo_planner')
module.CuroboPlanner = DisabledCuroboPlanner
sys.modules[module.__name__] = module
from hybrid_rollout.robodojo.robodojo_server.server import main
main()
