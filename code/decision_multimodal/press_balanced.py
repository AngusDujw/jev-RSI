"""Measured closed paired fingertips as a centered blunt pressing tool."""
import json
from pathlib import Path
import press_full
from robodojo_episode import save


def run(ep):
    save(ep.folder/'balanced_pair_plan.json',json.loads(Path(__file__).with_name('plans').joinpath('press_balanced_v1.json').read_text()))
    press_full.run(ep,balanced=True)
