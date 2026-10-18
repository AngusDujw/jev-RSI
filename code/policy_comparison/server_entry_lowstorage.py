"""Original server with redundant frame/video recording disabled only."""
from pathlib import Path
import runpy

# Patch the recording argument only. Fresh RGB/proprioception, native stepping,
# validation, physics and native terminal predicates remain the original code.
from hybrid_rollout.robodojo.robodojo_server.session import RoboDojoSession

original_observe = RoboDojoSession._observe


def observe_without_recording(self, record=False):
    return original_observe(self, record=False)


RoboDojoSession._observe = observe_without_recording
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')
