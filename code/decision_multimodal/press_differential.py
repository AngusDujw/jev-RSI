"""Independent rim-template feedback and bounded adaptive world-Z endpoints."""
import json
from pathlib import Path
from press_full import run as full
from robodojo_episode import save


def run(ep):
    plan=Path(__file__).with_name('plans')/'press_differential_v1.json'
    save(ep.folder/'fixed_plan.json',json.loads(plan.read_text()))
    return full(ep,balanced=True,independent_observer=True,anchored=True,differential=True)
